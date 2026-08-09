"""
Miru Assistant — Chat Analyzer 媒体处理数据模型。

语音转写 / 图片导出过程的中间数据结构。
"""

from dataclasses import dataclass, field

# 微信 4.x 图片 .dat 签名（6 字节）
DAT_SIG_V1 = bytes.fromhex("070856310807")  # AES 固定 key
DAT_SIG_V2 = bytes.fromhex("070856320807")  # AES key 从进程内存提取

# V1 固定 AES 密钥（ASCII 形式，16 字节；md5("0") 的前 16 个 hex 字符）
DAT_V1_AES_KEY = b"cfcd208495d565ef"

# V1 默认 XOR 密钥
DAT_V1_XOR_KEY = 0x88


@dataclass
class VoiceResult:
    """一条语音消息的转写结果。"""

    server_id: int = 0  # 与消息表 server_id 关联
    create_time: int = 0
    duration_ms: int = 0  # 语音时长（毫秒，来自 XML voicelength）
    text: str = ""  # 转写文本（失败为空串）
    ok: bool = False  # 是否成功转写
    error: str = ""  # 失败原因


@dataclass
class ImageResult:
    """一条图片消息的导出结果。"""

    md5: str = ""  # XML md5（CDN 原始 md5，可能不等于本地文件名）
    create_time: int = 0
    source_path: str = ""  # 源 .dat 路径（解密失败时也记录）
    export_path: str = ""  # 相对导出目录的路径（如 media/img/xxx.jpg）
    ok: bool = False  # 是否成功解密导出
    format: str = ""  # 嗅探到的格式: jpg/png/gif/webp/bmp/unknown
    error: str = ""  # 失败原因


@dataclass
class MediaExportResult:
    """一次导出的媒体处理汇总。"""

    voice_total: int = 0  # 语音消息总数
    voice_transcribed: int = 0  # 成功转写数
    voice_failed: int = 0  # 转写失败数
    image_total: int = 0  # 图片消息总数
    image_exported: int = 0  # 成功导出图片数
    image_failed: int = 0  # 解密失败（保留 .dat 原件）数
    media_dir: str = ""  # 媒体附件目录（相对输出目录，如 "media"）
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
