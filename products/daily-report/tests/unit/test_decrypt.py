"""
Miru Assistant — 解密模块单元测试 (Task 5B)。

测试覆盖:
    - SQLCipher 页面解密 (纯算法)
    - 密钥验证 (正确/错误密钥)
    - 数据库解密 + 写入临时文件
    - Schema 检查
    - DecryptResult 数据模型
    - 错误场景 (文件不存在/权限/格式错误)
    - 密钥提取 (mock)
"""

import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from miru.collector.wechat_db_decrypt import (
    DBSchema,
    DecryptResult,
    ExtractedKey,
    SQLCIPHER4_PAGE_SIZE,
    SQLCIPHER4_RESERVED_SIZE,
    SQLCIPHER4_USABLE_SIZE,
    SQLITE_MAGIC,
    _fill_schema,
    decrypt_and_open,
    decrypt_database_page,
    extract_keys_from_process,
    inspect_schema,
    try_decrypt_wechat_db,
    verify_decryption_key,
)
from miru.utils.errors import KeyExtractionError


# ============================================================
# Helpers
# ============================================================


def _create_sqlcipher_db(key: bytes, pages: int = 5) -> tuple[bytes, bytes]:
    """
    创建一个最小的 SQLCipher 4 加密数据库 (纯 Python 模拟)。

    SQLCipher 4 实际页面布局 (WeChat 4.x):
        - 页面大小: 4096 bytes
        - Reserved: 80 bytes (16 IV + 64 HMAC)
        - 加密负载: 4016 bytes (page 0: salt 包含在 CBC 加密链中)
        - 解密后 Page 0: 前 16 字节是 salt，需剥离

    Returns:
        (encrypted_db_bytes, key_used)
    """
    from Crypto.Cipher import AES
    from Crypto.Random import get_random_bytes

    usable = SQLCIPHER4_USABLE_SIZE          # 4016
    reserved = SQLCIPHER4_RESERVED_SIZE       # 80

    # 创建一个真实 SQLite 数据库
    import sqlite3
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = tmp.name
    tmp.close()

    conn = sqlite3.connect(tmp_path)
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT, value REAL)")
    conn.execute("INSERT INTO test_table VALUES (1, 'hello', 3.14)")
    conn.execute("INSERT INTO test_table VALUES (2, 'world', 2.71)")
    conn.commit()
    conn.close()

    with open(tmp_path, "rb") as f:
        plain_data = f.read()

    os.unlink(tmp_path)

    # 填充到页面边界
    total_pages = (len(plain_data) + usable - 1) // usable
    padded_size = total_pages * usable
    plain_data = plain_data + b"\x00" * (padded_size - len(plain_data))

    # 逐页加密 (SQLCipher 4 格式: salt 包含在 CBC 加密链中)
    db_salt = get_random_bytes(16)
    encrypted_pages = bytearray()

    for page_num in range(total_pages):
        iv = get_random_bytes(16)
        page = bytearray(SQLCIPHER4_PAGE_SIZE)

        if page_num == 0:
            # Page 0: DB salt 参与 CBC 加密链
            to_encrypt = db_salt + plain_data[0:4000]  # 16 + 4000 = 4016
            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            encrypted = cipher.encrypt(to_encrypt)
            page[0:len(encrypted)] = encrypted
        else:
            # Page N: 继续加密
            data_offset = 4000 + (page_num - 1) * 4016
            to_encrypt = plain_data[data_offset:data_offset + 4016]
            if len(to_encrypt) < 4016:
                to_encrypt = to_encrypt + b"\x00" * (4016 - len(to_encrypt))
            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            encrypted = cipher.encrypt(to_encrypt)
            page[0:len(encrypted)] = encrypted

        # Reserved area: IV + HMAC placeholder
        iv_offset = SQLCIPHER4_PAGE_SIZE - SQLCIPHER4_RESERVED_SIZE
        page[iv_offset:iv_offset + 16] = iv
        encrypted_pages.extend(page)

    return bytes(encrypted_pages), key


# ============================================================
# Test: Page Decryption (Core Algorithm)
# ============================================================


class TestPageDecryption:
    """测试单页解密算法。"""

    def test_decrypt_page0_has_magic(self):
        """解密 page 0 后 salt 已剥离，offset 0 处应是 SQLite magic header。"""
        from Crypto.Random import get_random_bytes
        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key)

        page0 = encrypted_db[:SQLCIPHER4_PAGE_SIZE]
        decrypted = decrypt_database_page(page0, key, page_number=0)

        # 解密后 salt 已剥离，magic 在 offset 0
        assert decrypted[:16] == SQLITE_MAGIC
        # SQLite header: magic(16) + page_size(2) + write_fmt(1 at offset 18) + read_fmt(1)
        assert decrypted[18] == 1  # write format version (offset 18 in SQLite header)

    def test_decrypt_page1_no_salt(self):
        """Page 1+ 不应该有 salt 前缀。"""
        from Crypto.Random import get_random_bytes
        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key, pages=3)

        page1 = encrypted_db[SQLCIPHER4_PAGE_SIZE:SQLCIPHER4_PAGE_SIZE * 2]
        decrypted = decrypt_database_page(page1, key, page_number=1)

        # Page 1 解密后不是空数据
        assert len(decrypted) == SQLCIPHER4_USABLE_SIZE
        # 数据不全是零
        assert any(b != 0 for b in decrypted[:50])

    def test_wrong_size_page_raises(self):
        """传入错误大小的页面应抛出 ValueError。"""
        with pytest.raises(ValueError, match="页面大小不匹配"):
            decrypt_database_page(b"\x00" * 1024, b"\x00" * 32, page_number=0)

    def test_decrypt_is_reproducible(self):
        """同一页面 + 同一密钥 = 相同结果。"""
        from Crypto.Random import get_random_bytes
        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key)
        page0 = encrypted_db[:SQLCIPHER4_PAGE_SIZE]

        d1 = decrypt_database_page(page0, key, page_number=0)
        d2 = decrypt_database_page(page0, key, page_number=0)

        assert d1 == d2


# ============================================================
# Test: Key Verification
# ============================================================


class TestKeyVerification:
    """测试密钥验证。"""

    def test_valid_key_passes(self, tmp_path):
        """正确密钥应返回 True。"""
        from Crypto.Random import get_random_bytes
        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key)

        db_file = tmp_path / "test.db"
        db_file.write_bytes(encrypted_db)

        valid, err = verify_decryption_key(db_file, key)
        assert valid is True
        assert err == ""

    def test_wrong_key_fails(self, tmp_path):
        """错误密钥应返回 False。"""
        from Crypto.Random import get_random_bytes
        key = get_random_bytes(32)
        wrong_key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key)

        db_file = tmp_path / "test.db"
        db_file.write_bytes(encrypted_db)

        valid, err = verify_decryption_key(db_file, wrong_key)
        assert valid is False
        assert "magic" in err.lower()

    def test_missing_file(self, tmp_path):
        """不存在的文件返回 False。"""
        valid, err = verify_decryption_key(
            tmp_path / "nonexistent.db",
            b"\x00" * 32,
        )
        assert valid is False
        assert "不存在" in err

    def test_file_too_small(self, tmp_path):
        """过小的文件返回 False。"""
        small = tmp_path / "small.db"
        small.write_bytes(b"\x00" * 100)

        valid, err = verify_decryption_key(small, b"\x00" * 32)
        assert valid is False


# ============================================================
# Test: Full Decrypt & Open
# ============================================================


class TestDecryptAndOpen:
    """测试完整解密并打开。"""

    def test_decrypt_and_open_succeeds(self, tmp_path):
        """解密临时文件可被 sqlite3 打开。"""
        import sqlite3
        from Crypto.Random import get_random_bytes

        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key, pages=3)

        db_file = tmp_path / "encrypted.db"
        db_file.write_bytes(encrypted_db)

        temp_path, err = decrypt_and_open(db_file, key)
        assert temp_path is not None
        assert err == ""
        assert temp_path.exists()

        # 可用 sqlite3 打开
        conn = sqlite3.connect(str(temp_path))
        rows = conn.execute("SELECT * FROM test_table ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0][1] == "hello"
        assert rows[1][1] == "world"
        conn.close()

        temp_path.unlink(missing_ok=True)

    def test_missing_file(self):
        """不存在的文件返回 None + error。"""
        temp_path, err = decrypt_and_open(
            Path("/nonexistent/db.db"),
            b"\x00" * 32,
        )
        assert temp_path is None
        assert err != ""

    def test_wrong_size_file(self, tmp_path):
        """非整数倍页面大小的文件返回 None。"""
        bad_db = tmp_path / "bad.db"
        bad_db.write_bytes(b"\x00" * 5000)  # Not a multiple of 4096

        temp_path, err = decrypt_and_open(bad_db, b"\x00" * 32)
        assert temp_path is None
        assert "整数倍" in err


# ============================================================
# Test: Schema Inspection
# ============================================================


class TestSchemaInspection:
    """测试 schema 检查。"""

    def test_inspect_basic_schema(self, tmp_path):
        """基本 schema 检查。"""
        import sqlite3

        db_file = tmp_path / "schema_test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        conn.execute("CREATE TABLE posts (id INTEGER PRIMARY KEY, title TEXT, body TEXT, user_id INTEGER)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@test.com')")
        conn.commit()
        conn.close()

        schema = inspect_schema(db_file)

        assert schema.sqlite_version != ""
        assert schema.page_count > 0
        assert schema.page_size > 0
        assert "users" in schema.tables
        assert "posts" in schema.tables
        assert len(schema.table_details["users"]) == 3
        assert schema.table_details["users"][0] == ("id", "INTEGER", True)
        assert schema.row_counts["users"] == 1

    def test_inspect_empty_db(self, tmp_path):
        """空数据库也应该有 sqlite_master (0 个用户表)。"""
        import sqlite3

        db_file = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_file))
        conn.close()

        schema = inspect_schema(db_file)
        assert schema.tables == [] or schema.tables == []


# ============================================================
# Test: DecryptResult
# ============================================================


class TestDecryptResult:
    """测试 DecryptResult 数据模型。"""

    def test_default_values(self):
        """默认值检查。"""
        r = DecryptResult()
        assert r.success is False
        assert r.key_found is False
        assert r.is_encrypted is True
        assert r.is_decrypted is False

    def test_unencrypted_db_handled(self, tmp_path):
        """未加密的 SQLite 文件应被正确识别。"""
        import sqlite3

        db_file = tmp_path / "plain.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (a INTEGER)")
        conn.close()

        result = try_decrypt_wechat_db(
            db_path=db_file,
            pid=9999,
            keys=[],
        )

        assert result.success is True
        assert result.is_encrypted is False
        assert result.is_decrypted is True
        assert "t" in result.tables


# ============================================================
# Test: Key Extraction (Mock)
# ============================================================


class TestKeyExtraction:
    """测试密钥提取逻辑。"""

    def test_process_not_found_raises(self):
        """PID 不存在时抛出 KeyExtractionError。"""
        with pytest.raises(KeyExtractionError, match="无法打开"):
            extract_keys_from_process(999999)

    def test_no_keys_found(self):
        """未扫描到任何密钥时抛出异常。"""
        with patch(
            "miru.collector.wechat_db_decrypt._scan_process_memory",
            return_value=[],
        ):
            # pymem 是在 extract_keys_from_process 函数内部 import 的
            with patch("pymem.Pymem") as mock_pymem_cls:
                mock_pm = MagicMock()
                mock_pymem_cls.return_value = mock_pm
                mock_pm.list_modules.return_value = []

                with pytest.raises(KeyExtractionError, match="未在微信进程内存中找到任何密钥"):
                    extract_keys_from_process(12345)


# ============================================================
# Test: ExtractedKey Model
# ============================================================


class TestExtractedKeyModel:
    """测试密钥数据模型。"""

    def test_key_model(self):
        """基本字段测试。"""
        k = ExtractedKey(
            raw_key=b"\x01" * 32,
            salt=b"\x02" * 16,
            hex_key="01" * 32 + "02" * 16,
        )
        assert len(k.raw_key) == 32
        assert len(k.salt) == 16
        assert k.verified is False

    def test_key_verified_flag(self):
        """verified 标志可以设置。"""
        k = ExtractedKey(
            raw_key=b"\x03" * 32,
            salt=b"\x04" * 16,
            hex_key="test",
            verified=True,
            db_name="message_0.db",
        )
        assert k.verified is True
        assert k.db_name == "message_0.db"


# ============================================================
# Test: _fill_schema Helper
# ============================================================


class TestFillSchema:
    """测试 _fill_schema 辅助函数。"""

    def test_fill_schema_populates_result(self, tmp_path):
        """_fill_schema 正确填充 DecryptResult。"""
        import sqlite3

        db_file = tmp_path / "fill_test.db"
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, desc TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'test')")
        conn.commit()
        conn.close()

        result = DecryptResult()
        _fill_schema(result, db_file)

        assert "items" in result.tables
        assert len(result.table_details["items"]) == 2
        assert result.sqlite_version != ""


# ============================================================
# Test: End-to-End Decryption Pipeline (Mock Environment)
# ============================================================


class TestDecryptionPipeline:
    """解密完整 Pipeline 测试。"""

    def test_pipeline_with_encrypted_db(self, tmp_path):
        """使用合成加密数据库测试完整 Pipeline。"""
        from Crypto.Random import get_random_bytes

        key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key, pages=3)

        db_file = tmp_path / "enc.db"
        db_file.write_bytes(encrypted_db)

        fake_key = ExtractedKey(
            raw_key=key,
            salt=b"\x00" * 16,
            hex_key=key.hex(),
        )

        result = try_decrypt_wechat_db(
            db_path=db_file,
            pid=12345,
            keys=[fake_key],
        )

        assert result.success is True
        assert result.key_found is True
        assert result.is_encrypted is True
        assert result.is_decrypted is True
        assert "test_table" in result.tables

    def test_pipeline_with_wrong_key(self, tmp_path):
        """错误密钥导致解密失败。"""
        from Crypto.Random import get_random_bytes

        key = get_random_bytes(32)
        wrong_key = get_random_bytes(32)
        encrypted_db, _ = _create_sqlcipher_db(key, pages=3)

        db_file = tmp_path / "enc2.db"
        db_file.write_bytes(encrypted_db)

        fake_key = ExtractedKey(
            raw_key=wrong_key,
            salt=b"\x00" * 16,
            hex_key=wrong_key.hex(),
        )

        result = try_decrypt_wechat_db(
            db_path=db_file,
            pid=12345,
            keys=[fake_key],
        )

        assert result.success is False
        assert result.error_stage == "decrypt"

    def test_pipeline_file_not_found(self):
        """文件不存在时返回清晰的错误。"""
        result = try_decrypt_wechat_db(
            db_path=Path("/nonexistent/file.db"),
            pid=12345,
            keys=[],
        )

        assert result.success is False
        assert result.error_stage == "process"


# ============================================================
# Test: SQLCipher Constants
# ============================================================


class TestConstants:
    """测试常量正确性。"""

    def test_page_size_is_4096(self):
        """SQLCipher 4 页面大小 = 4096。"""
        assert SQLCIPHER4_PAGE_SIZE == 4096

    def test_usable_plus_reserved_equals_page_size(self):
        """usable + reserved = 4096。"""
        assert SQLCIPHER4_USABLE_SIZE + SQLCIPHER4_RESERVED_SIZE == SQLCIPHER4_PAGE_SIZE

    def test_sqlite_magic_is_correct(self):
        """SQLite magic header 正确。"""
        assert SQLITE_MAGIC == b"SQLite format 3\x00"
        assert len(SQLITE_MAGIC) == 16
