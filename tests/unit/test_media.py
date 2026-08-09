"""
Miru Assistant — 媒体处理（语音转写 + 图片导出）单元测试。

覆盖:
    - .dat V1 文件头解析与 AES+XOR 解密（构造加密样本验证）
    - 图片格式嗅探
    - attach 目录定位（MD5(wxid) + 年月）
    - VoiceInfo 查询与 server_id 关联
    - processor 编排（语音渲染文本 / 图片渲染文本 / 失败降级）
"""

import hashlib
import io
import sqlite3
from pathlib import Path

import pytest

from miru.chat_analyzer.media.image import ImageExtractor
from miru.chat_analyzer.media.models import DAT_SIG_V1, DAT_SIG_V2, DAT_V1_AES_KEY, DAT_V1_XOR_KEY
from miru.chat_analyzer.media.processor import (
    MediaConfig,
    MediaProcessor,
    _format_duration,
    _parse_voice_length,
)
from miru.chat_analyzer.media.voice import VoiceExtractor
from miru.chat_analyzer.models import ChatMessage

SELF_WXID = "wxid_self"
CONTACT_WXID = "wxid_krista_test"
CONTACT_NAME = "Krista"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


# ============================================================
# Helpers — 构造 V1 加密 .dat 样本
# ============================================================


def make_v1_dat(image_bytes: bytes, aes_key: bytes = DAT_V1_AES_KEY, xor_key: int = DAT_V1_XOR_KEY) -> bytes:
    """按 V1 格式构造 .dat：AES 段(前 1024B) + 明文段 + XOR 段。"""
    from Crypto.Cipher import AES

    # 三段: AES 加密前 1024 字节（不足则用图片数据填充）+ 中间明文 + 尾部 XOR
    aes_size = 1024
    if len(image_bytes) > 1024:
        # 尾部 512 字节 XOR 加密，其余明文
        raw_len = len(image_bytes) - 512
        aes_data = image_bytes[:1024]
        raw_seg = image_bytes[1024:raw_len]
        xor_seg = bytes(b ^ xor_key for b in image_bytes[raw_len:])
    else:
        aes_data = image_bytes
        raw_seg = b""
        xor_seg = b""

    # PKCS7 填充 AES 段
    pad = 16 - (len(aes_data) % 16)
    aes_padded = aes_data + bytes([pad]) * pad
    cipher = AES.new(aes_key, AES.MODE_ECB)
    aes_enc = cipher.encrypt(aes_padded)

    header = DAT_SIG_V1 + aes_size.to_bytes(4, "little") + len(xor_seg).to_bytes(4, "little") + b"\x01"
    return header + aes_enc + raw_seg + xor_seg


def _jpeg_bytes() -> bytes:
    """构造一个带 JPEG 魔数头尾的假图片。"""
    return b"\xff\xd8\xff\xe0" + b"JFIF" + b"\x00" * 2000 + b"\xff\xd9"


# ============================================================
# Test: .dat 解析与解密
# ============================================================


class TestDatDecrypt:
    def test_parse_header_v1(self):
        dat = make_v1_dat(_jpeg_bytes())
        stype, aes_size, xor_size = ImageExtractor.parse_header(dat)
        assert stype == "v1"
        assert aes_size == 1024
        assert xor_size == 512

    def test_parse_header_unknown(self):
        assert ImageExtractor.parse_header(b"\x00" * 20) is None
        assert ImageExtractor.parse_header(b"short") is None

    def test_v1_roundtrip(self, tmp_path: Path):
        img = _jpeg_bytes()
        dat_path = tmp_path / "test.dat"
        dat_path.write_bytes(make_v1_dat(img))

        ex = ImageExtractor(tmp_path)
        decrypted = ex.decrypt(dat_path)
        assert decrypted is not None
        assert decrypted == img

    def test_sniff_formats(self):
        ex = ImageExtractor(".")
        assert ex.sniff_format(b"\xff\xd8\xff\xe0JFIF") == "jpg"
        assert ex.sniff_format(b"\x89PNG\r\n\x1a\n") == "png"
        assert ex.sniff_format(b"GIF89a") == "gif"
        assert ex.sniff_format(b"RIFF\x00\x00\x00\x00WEBP") == "webp"
        assert ex.sniff_format(b"BM\x00\x00") == "bmp"
        assert ex.sniff_format(b"random") == "unknown"


# ============================================================
# Test: attach 目录定位
# ============================================================


class TestAttachLocate:
    def _make_attach(self, root: Path, wxid: str, month: str, dat_name: str, mtime: float) -> Path:
        img_dir = root / "msg" / "attach" / _md5(wxid) / month / "Img"
        img_dir.mkdir(parents=True, exist_ok=True)
        p = img_dir / dat_name
        p.write_bytes(make_v1_dat(_jpeg_bytes()))
        import os

        os.utime(p, (mtime, mtime))
        return p

    def test_session_dir_matches_msg_table_hash(self):
        # attach 目录 = MD5(wxid) = 会话表名 Msg_{...} 的哈希部分
        assert _md5(CONTACT_WXID) == ImageExtractor._session_dir(CONTACT_WXID)

    def test_locate_by_md5(self, tmp_path: Path):
        ex = ImageExtractor(tmp_path)
        self._make_attach(tmp_path, CONTACT_WXID, "2026-07", "aabb.dat", 1_785_000_000)
        cands = ex.locate_files(CONTACT_WXID, 1_785_000_000, md5="aabb")
        assert len(cands) == 1
        assert cands[0].name == "aabb.dat"

    def test_locate_pick_by_time(self, tmp_path: Path):
        ex = ImageExtractor(tmp_path)
        t = 1_785_000_000
        self._make_attach(tmp_path, CONTACT_WXID, "2026-07", "old.dat", t - 5000)
        self._make_attach(tmp_path, CONTACT_WXID, "2026-07", "new.dat", t)
        cands = ex.locate_files(CONTACT_WXID, t)
        picked = ex.pick_by_time(cands, t, window_s=3600)
        assert picked is not None
        assert picked.name == "new.dat"

    def test_pick_by_time_outside_window(self, tmp_path: Path):
        ex = ImageExtractor(tmp_path)
        t = 1_785_000_000
        self._make_attach(tmp_path, CONTACT_WXID, "2026-07", "far.dat", t - 7200)
        cands = ex.locate_files(CONTACT_WXID, t)
        assert ex.pick_by_time(cands, t, window_s=3600) is None

    def test_export_writes_image(self, tmp_path: Path):
        ex = ImageExtractor(tmp_path)
        t = 1_785_000_000
        self._make_attach(tmp_path, CONTACT_WXID, "2026-07", "aabbcc.dat", t)
        media_dir = tmp_path / "media"
        data, ext, dat_path = ex.export(CONTACT_WXID, t, md5="aabbcc", export_dir=media_dir)
        assert data  # 解密成功
        assert ext == "jpg"
        out = media_dir / "aabbcc.jpg"
        assert out.exists()


# ============================================================
# Test: VoiceInfo 查询
# ============================================================


def _make_media_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE VoiceInfo (chat_name_id INTEGER, create_time INTEGER, local_id INTEGER, svr_id INTEGER, voice_data BLOB, data_index TEXT)")
    conn.execute(
        "INSERT INTO VoiceInfo VALUES (1, 1785000000, 1, 50001, X'02232153494c4b5f5633', '0')"
    )
    conn.execute(
        "INSERT INTO VoiceInfo VALUES (1, 1785000000, 2, 50002, X'02232153494c4b5f5633', '0')"
    )
    conn.commit()
    conn.close()


@pytest.fixture
def media_db(tmp_path: Path):
    """构造含 media_0.db 的模拟账号目录。"""
    acct = tmp_path / f"{SELF_WXID}_a01"
    msg_dir = acct / "db_storage" / "message"
    msg_dir.mkdir(parents=True)
    _make_media_db(msg_dir / "media_0.db")

    from miru.chat_analyzer.offline_reader import OfflineWeChatDB

    db = OfflineWeChatDB(str(acct))
    yield db
    db.close()


class TestVoiceExtractor:
    def test_get_voice_data_by_server_id(self, media_db):
        ex = VoiceExtractor(media_db)
        data = ex.get_voice_data(50001)
        assert data is not None
        assert data[:10] == b"\x02\x23!SILK_V3"

    def test_get_voice_missing(self, media_db):
        ex = VoiceExtractor(media_db)
        assert ex.get_voice_data(99999) is None

    def test_iter_voice_ids(self, media_db):
        ex = VoiceExtractor(media_db)
        result = ex.iter_voice_ids([50001, 50002, 99999])
        assert set(result) == {50001, 50002}

    def test_pcm_to_wav(self):
        wav = VoiceExtractor.pcm_to_wav_bytes(b"\x00" * 3200, sample_rate=16000)
        assert wav[:4] == b"RIFF"
        assert b"WAVE" in wav[:16]


# ============================================================
# Test: processor 编排
# ============================================================


def _make_msg(msg_type: int, server_id: int = 0, content: str = "", ts: int = 1_785_000_000) -> ChatMessage:
    return ChatMessage(
        timestamp=ts,
        sender="Krista",
        content=content,
        msg_type=msg_type,
        server_id=server_id,
    )


class TestProcessor:
    def test_voice_fallback_with_duration(self):
        msg = _make_msg(34, content='<voicemsg voicelength = "3000" />')
        text = MediaProcessor._voice_fallback(msg)
        assert text == "[语音] (时长 3s)"

    def test_voice_fallback_no_duration(self):
        msg = _make_msg(34, content="")
        assert MediaProcessor._voice_fallback(msg) == "[语音]"

    def test_image_override_text(self, tmp_path: Path):
        # 构造 attach 中的 V1 图片（账号目录 = tmp_path/wxid_self_a01）
        acct = tmp_path / f"{SELF_WXID}_a01"
        img_dir = acct / "msg" / "attach" / _md5(CONTACT_WXID) / "2026-07" / "Img"
        img_dir.mkdir(parents=True)
        (img_dir / "11223344.dat").write_bytes(make_v1_dat(_jpeg_bytes()))
        import os

        os.utime(img_dir / "11223344.dat", (1_785_000_000, 1_785_000_000))

        # 模拟 db（无 media_0.db 也可，语音不触发）
        msg_dir = acct / "db_storage" / "message"
        msg_dir.mkdir(parents=True)
        conn = sqlite3.connect(str(msg_dir / "media_0.db"))
        conn.execute("CREATE TABLE VoiceInfo (chat_name_id INTEGER, create_time INTEGER, local_id INTEGER, svr_id INTEGER, voice_data BLOB, data_index TEXT)")
        conn.commit()
        conn.close()

        from miru.chat_analyzer.offline_reader import OfflineWeChatDB

        db = OfflineWeChatDB(str(acct))
        proc = MediaProcessor(acct, db, MediaConfig(voice_transcribe=False, images=True))
        msg = _make_msg(3, content='<img md5="11223344abcdef0123456789abcdef01" />')
        media_dir = tmp_path / "media"
        result, overrides = proc.process([msg], CONTACT_WXID, media_dir)
        assert result.image_total == 1
        assert result.image_exported == 1
        assert overrides[0].startswith("[图片] media/img/")
        assert (media_dir / "img" / "11223344abcdef01.jpg").exists()
        db.close()

    def test_voice_missing_data_fallback(self, tmp_path: Path):
        """语音无 VoiceInfo 数据 → 降级占位，不崩溃。"""
        acct = tmp_path / f"{SELF_WXID}_a01"
        msg_dir = acct / "db_storage" / "message"
        msg_dir.mkdir(parents=True)
        _make_media_db(msg_dir / "media_0.db")

        from miru.chat_analyzer.offline_reader import OfflineWeChatDB

        db = OfflineWeChatDB(str(acct))
        proc = MediaProcessor(
            acct,
            db,
            MediaConfig(voice_transcribe=True, images=False),
        )
        proc.stt = None  # 禁用真实 STT
        msg = _make_msg(34, server_id=99999, content='<voicemsg voicelength = "2000" />')
        result, overrides = proc.process([msg], CONTACT_WXID, tmp_path / "media")
        assert result.voice_total == 1
        assert result.voice_failed == 1
        assert overrides[0] == "[语音] (时长 2s)"
        db.close()


# ============================================================
# Test: V2 密钥磁盘派生（derive_key_from_disk）
# ============================================================


def _make_v2_dat_for_key(aes_key: bytes, xor_key: int, image: bytes) -> bytes:
    """按 V2 格式构造 .dat（用于派生算法测试）。"""
    from Crypto.Cipher import AES

    aes_size = 256
    aes_data = image[:256]
    pad = 16 - (len(aes_data) % 16)
    aes_enc = AES.new(aes_key, AES.MODE_ECB).encrypt(aes_data + bytes([pad]) * pad)
    xor_seg = bytes(b ^ xor_key for b in image[256:])
    header = DAT_SIG_V2 + aes_size.to_bytes(4, "little") + len(xor_seg).to_bytes(4, "little") + b"\x01"
    return header + aes_enc + xor_seg


class TestDeriveKeyFromDisk:
    def test_derive_roundtrip(self, tmp_path: Path):
        """用已知 uin 构造账号目录 → 派生算法应还原 aes_key。"""
        import hashlib
        import os

        uin = 123456789
        suffix = hashlib.md5(str(uin).encode()).hexdigest()[:4]
        wxid_norm = "wxid_derivetest"
        acct = tmp_path / f"{wxid_norm}_{suffix}"
        aes_key = hashlib.md5(f"{uin}{wxid_norm}".encode()).hexdigest()[:16].encode("ascii")
        xor_key = uin & 0xFF

        # 构造 attach/_t.dat（JPEG 头尾数据）
        img = b"\xff\xd8\xff\xe0" + b"JFIF" + b"\x00" * 400 + b"\xff\xd9"
        tdir = acct / "msg" / "attach" / "deadbeef" / "2026-07" / "Img"
        tdir.mkdir(parents=True)
        for i in range(3):
            p = tdir / f"thumb_{i}_t.dat"
            p.write_bytes(_make_v2_dat_for_key(aes_key, xor_key, img))
            os.utime(p, (1_785_000_000 + i, 1_785_000_000 + i))

        from miru.chat_analyzer.media.v2key import derive_key_from_disk

        keys = derive_key_from_disk(acct)
        assert keys, "磁盘派生应成功"
        assert keys[0] == aes_key

    def test_derive_no_account_suffix(self, tmp_path: Path):
        """无 _xxxx 后缀的目录 → 无法派生（返回空）。"""
        from miru.chat_analyzer.media.v2key import derive_key_from_disk

        acct = tmp_path / "wxid_nosuffix"
        (acct / "msg" / "attach").mkdir(parents=True)
        assert derive_key_from_disk(acct) == []

    def test_derive_no_attach(self, tmp_path: Path):
        """无 attach 目录 → 返回空。"""
        from miru.chat_analyzer.media.v2key import derive_key_from_disk

        acct = tmp_path / f"wxid_test_{'abcd'}"
        acct.mkdir()
        assert derive_key_from_disk(acct) == []


# ============================================================
# Test: offline_exporter 集成（media_config 参数 + overrides 渲染）
# ============================================================


class TestExporterIntegration:
    def test_export_with_media_voice(self, tmp_path: Path):
        """导出时开启语音媒体 → chat.txt 中语音消息渲染转写占位。"""
        from miru.chat_analyzer.offline_exporter import ContactFullExporter

        acct = tmp_path / f"{SELF_WXID}_a01"
        storage = acct / "db_storage"
        (storage / "contact").mkdir(parents=True)
        (storage / "message").mkdir(parents=True)

        # contact.db
        conn = sqlite3.connect(str(storage / "contact" / "contact.db"))
        conn.execute("CREATE TABLE contact (username TEXT, alias TEXT, remark TEXT, nick_name TEXT)")
        conn.execute("INSERT INTO contact VALUES (?, '', '', ?)", (CONTACT_WXID, CONTACT_NAME))
        conn.commit()
        conn.close()

        # message_0.db: 文本 + 语音消息
        conn = sqlite3.connect(str(storage / "message" / "message_0.db"))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, ?)", (SELF_WXID,))
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, ?)", (CONTACT_WXID,))
        table = f"Msg_{_md5(CONTACT_WXID)}"
        conn.execute(f"""
            CREATE TABLE [{table}] (
                local_id INTEGER, server_id INTEGER, local_type INTEGER DEFAULT 1,
                real_sender_id INTEGER DEFAULT 0, create_time INTEGER,
                sort_seq INTEGER, message_content BLOB
            )
        """)
        base = 1_785_000_000
        conn.execute(
            f"INSERT INTO [{table}] VALUES (1, 50001, 34, 2, ?, 1, ?)",
            (base, '<voicemsg voicelength = "3000" />'),
        )
        conn.execute(
            f"INSERT INTO [{table}] VALUES (2, 50002, 1, 1, ?, 2, ?)",
            (base + 60, "你好呀"),
        )
        conn.commit()
        conn.close()

        # media_0.db（VoiceInfo 无该语音 → 走失败降级）
        conn = sqlite3.connect(str(storage / "message" / "media_0.db"))
        conn.execute("CREATE TABLE VoiceInfo (chat_name_id INTEGER, create_time INTEGER, local_id INTEGER, svr_id INTEGER, voice_data BLOB, data_index TEXT)")
        conn.commit()
        conn.close()

        # 禁用真实 STT（不下载模型）：stt=STTEngine 注入为 None 的处理器
        from miru.chat_analyzer.media.processor import MediaConfig, MediaProcessor

        class _NoSttProcessor(MediaProcessor):
            def __init__(self, account_dir, db, config):
                super().__init__(account_dir, db, config, stt=None)

        exporter = ContactFullExporter(data_root=str(acct))
        exporter._processor_cls = _NoSttProcessor  # type: ignore[attr-defined]

        result = exporter.export(
            contact_name=CONTACT_NAME,
            output_dir=str(tmp_path / "out"),
            media_config=MediaConfig(voice_transcribe=True, images=False),
        )
        assert result.success
        chat = Path(result.output_file).read_text(encoding="utf-8")
        assert "[语音] (时长 3s)" in chat  # 转写失败降级占位
        assert "你好呀" in chat
        assert result.voice_failed >= 0  # 语音失败数 ≥ 0（降级不崩溃）

    def test_export_without_media_keeps_placeholder(self, tmp_path: Path):
        """不传 media_config → 保持原有 [语音] 摘要行为。"""
        from miru.chat_analyzer.offline_exporter import ContactFullExporter

        acct = tmp_path / f"{SELF_WXID}_a01"
        storage = acct / "db_storage"
        (storage / "contact").mkdir(parents=True)
        (storage / "message").mkdir(parents=True)
        conn = sqlite3.connect(str(storage / "contact" / "contact.db"))
        conn.execute("CREATE TABLE contact (username TEXT, alias TEXT, remark TEXT, nick_name TEXT)")
        conn.execute("INSERT INTO contact VALUES (?, '', '', ?)", (CONTACT_WXID, CONTACT_NAME))
        conn.commit()
        conn.close()

        conn = sqlite3.connect(str(storage / "message" / "message_0.db"))
        conn.execute("CREATE TABLE Name2Id (user_name TEXT)")
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (1, ?)", (SELF_WXID,))
        conn.execute("INSERT INTO Name2Id (rowid, user_name) VALUES (2, ?)", (CONTACT_WXID,))
        table = f"Msg_{_md5(CONTACT_WXID)}"
        conn.execute(f"""
            CREATE TABLE [{table}] (
                local_id INTEGER, server_id INTEGER, local_type INTEGER DEFAULT 1,
                real_sender_id INTEGER DEFAULT 0, create_time INTEGER,
                sort_seq INTEGER, message_content BLOB
            )
        """)
        conn.execute(
            f"INSERT INTO [{table}] VALUES (1, 50001, 34, 2, 1785000000, 1, ?)",
            ('<voicemsg voicelength = "3000" />',),
        )
        conn.commit()
        conn.close()

        exporter = ContactFullExporter(data_root=str(acct))
        result = exporter.export(contact_name=CONTACT_NAME, output_dir=str(tmp_path / "out"))
        assert result.success
        chat = Path(result.output_file).read_text(encoding="utf-8")
        assert "[语音] (时长 3s)" in chat
        assert result.media_dir == ""  # 未启用媒体


# ============================================================
# Test: 工具函数
# ============================================================


class TestUtils:
    def test_parse_voice_length(self):
        assert _parse_voice_length('<voicemsg voicelength = "5060"  voiceformat="4" />') == 5060
        assert _parse_voice_length('<voicemsg voicelength="5000" />') == 5000
        assert _parse_voice_length("") == 0
        assert _parse_voice_length("<voicemsg />") == 0

    def test_format_duration(self):
        assert _format_duration(3000) == "3s"
        assert _format_duration(5060) == "5s"
        assert _format_duration(0) == ""
        assert _format_duration(500) == "1s"
