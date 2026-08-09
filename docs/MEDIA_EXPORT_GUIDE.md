# Miru 媒体导出功能完整指南（语音转写 + 图片保留）

> 本文档详细记录 Miru Chat Analyzer 的媒体导出功能（V2 新增，默认开启）：
> 语音消息自动转写为文字、图片消息自动解密保留。包含使用方法、配置说明、
> 技术原理、常见问题与性能参考，供日后维护查阅。
>
> 最后更新：2026-08-09（提交 a079ced）

---

## 目录

1. [功能总览](#1-功能总览)
2. [前提条件](#2-前提条件)
3. [快速开始](#3-快速开始)
4. [配置详解](#4-配置详解)
5. [输出文件说明](#5-输出文件说明)
6. [技术原理](#6-技术原理)
7. [常见问题 FAQ](#7-常见问题-faq)
8. [性能参考（实测数据）](#8-性能参考实测数据)
9. [维护与故障排查](#9-维护与故障排查)

---

## 1. 功能总览

导出联系人聊天记录时（`miru export` / `analyze_all.py`），自动附带两项媒体处理：

### 1.1 语音转文字（voice_transcribe）

- **干什么**：把聊天中的每条语音消息（微信 4.x 存为 SILK 格式）自动转写为中文文本
- **效果**：chat.txt 中语音消息显示为 `[语音转文字] 我明天下午三点到（时长 4s）`，不再是 `[语音] (时长 4s)` 占位
- **引擎**：本地 faster-whisper（CTranslate2 加速），**完全离线，不上传任何数据**
- **缓存**：转写结果缓存到 `data/stt_cache.json`，重复导出秒回，不重复转写

### 1.2 图片保留（images）

- **干什么**：把聊天中的图片消息解密并导出到 `media/img/` 目录，chat.txt 引用路径
- **效果**：chat.txt 中图片消息显示 `[图片] media/img/xxxx.jpg`，图片文件可直接打开
- **格式策略**（重要，见 [技术原理 6.3](#63-为什么图片要分jpg和wxgf两种文件)）：
  - `xxx.jpg` — 微信标准缩略图（颜色正确、可直接查看，90~400px）
  - `xxx.wxgf` — 高清原图备份（微信私有 HEVC 格式，仅微信客户端可正常查看）

### 1.3 默认状态

两项功能**默认开启**（settings.yaml 的 `miru.export.media` 段），无需任何参数。

---

## 2. 前提条件

| 依赖 | 是否必须 | 说明 |
|---|---|---|
| 微信 PC 4.x 已登录的数据目录 | ✅ 必须 | 自动检测，或 settings.yaml `wechat.data_dir` 指定 |
| `database_keys.yaml` / `all_keys.json` | ✅ 必须 | 已有（离线导出本身就依赖它） |
| `pysilk`（pip 包） | ✅ 必须 | SILK 语音解码，已加入 requirements.txt |
| `faster-whisper`（pip 包） | ✅ 必须 | 语音转写，已加入 requirements.txt |
| whisper 模型文件 | ⚠️ 首次自动下载 | 存于 `data/models/faster-whisper-<模型>/`，约 75MB(tiny) ~ 460MB(small) |
| ffmpeg | ❌ 非必须 | 仅 `convert_wxgf` 批量转换时需要（本机已装 8.1.2） |
| 微信进程运行 | ❌ 非必须 | 媒体导出完全离线，不需要微信运行 |

---

## 3. 快速开始

### 3.1 命令行（推荐）

```bash
# 导出单个联系人（默认带媒体：语音转写 + 图片）
miru export --contact Krista

# 跳过 AI 分析（省钱），媒体仍开启
miru export --contact Krista --skip-analyze

# 导出白名单全部联系人
miru export --all

# 强制开关媒体
miru export --contact Krista --with-media    # 强制开启
miru export --contact Krista --no-media      # 强制关闭
```

### 3.2 批量脚本（并行加速）

```bash
# 白名单全部 3 人，3 路并行（默认 --parallel 3）
python scripts/analyze_all.py

# 指定联系人 + 跳过 AI 分析
python scripts/analyze_all.py --contacts Krista --skip-analyze

# 并行数量（语音转写可并行加速）
python scripts/analyze_all.py --parallel 3
```

### 3.3 代码调用

```python
from miru.chat_analyzer.offline_exporter import ContactFullExporter
from miru.chat_analyzer.media.processor import MediaConfig

exporter = ContactFullExporter()
result = exporter.export(
    contact_name="Krista",
    wxid="wxid_ixvb8uon0dci22",
    output_dir="output",
    media_config=MediaConfig(),  # 默认全部开启
)
print(result.voice_transcribed, result.image_exported)  # 统计
```

---

## 4. 配置详解

`config/settings.yaml` 的 `miru.export.media` 段：

```yaml
miru:
  export:
    media:
      enabled: true            # 总开关：false 关闭全部媒体处理
      images: true             # 图片导出
      voice_transcribe: true   # 语音转文字
      stt_model: "small"       # faster-whisper 模型：tiny/base/small/medium
      stt_cache: true          # 转写结果缓存（data/stt_cache.json）
      keep_voice_files: false  # 是否在 media/voice/ 保留语音 WAV 原件
      convert_wxgf: true       # wxgf 转 jpg（当前为缩略图策略，见 FAQ）
```

### 配置项说明

| 配置 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `images` | `true` | 图片导出 |
| `voice_transcribe` | `true` | 语音转写 |
| `stt_model` | `"small"` | **模型越大越准越慢**。small 中文效果好；tiny 快 3~5 倍质量略降。**转写缓存跨模型复用**——先用 tiny 跑一遍填充缓存，再换 small 不用重转 |
| `stt_cache` | `true` | 缓存转写结果。**强烈建议保持开启**（重复导出免重转） |
| `keep_voice_files` | `false` | 额外保留 WAV 语音原件（`media/voice/voice_<svr_id>.wav`） |
| `convert_wxgf` | `true` | 控制 wxgf→jpg 转换。当前实现下 wxgf 为高清备份、jpg 来自缩略图，此开关影响备份逻辑 |

---

## 5. 输出文件说明

```
output/
└── Krista/
    ├── chat.txt            # 可读版（语音行含转写文本，图片行含路径）
    ├── chat_raw.txt        # 原始完整版（含 XML，不变）
    ├── analysis.md         # AI 分析报告（--skip-analyze 时无）
    ├── statistics.json     # 统计
    ├── timeline.json       # 时间线
    └── media/
        └── img/
            ├── 202673abfe80197e.jpg    # 缩略图（标准 jpg，可查看）
            ├── 202673abfe80197e.wxgf   # 高清原图备份（微信私有格式）
            └── xxxx.dat                # 解密失败保留的原件（极少数）
```

### chat.txt 中的渲染格式

```
[2026-07-31 09:46] Krista：
[语音转文字] 我感觉我一出去他们就知道我现在还没有睡觉（时长 4s）

[2026-07-31 10:58] 我：
[图片] media/img/202673abfe80197e.jpg

[2026-07-31 11:02] Krista：
[图片未解密] media/img/xxx.dat        # 解密失败的极少数情况
```

---

## 6. 技术原理

### 6.1 语音提取（零依赖，可靠）

- **数据源**：`db_storage/message/media_0.db` 的 `VoiceInfo` 表（每台微信约 1.3 万条语音）
- **关联**：`VoiceInfo.svr_id` = 消息表 `server_id`，全量交叉验证命中率 **99.99%**
- **格式**：`voice_data` 是 SILK V3 编码（微信版头部多 `\x02` 字节），pysilk 库直接解码（兼容微信格式）
- **流程**：SILK → PCM(16kHz mono) → WAV → faster-whisper 转写（`vad_filter=True` 跳过静音）
- **缓存 key**：WAV 内容的 md5（与模型无关，跨模型复用）

### 6.2 图片解密（磁盘密钥派生，无需微信运行）

微信 4.x 图片 `.dat` 加密格式（签名 `07 08 56 32 08 07` = V2）：

```
[6B 签名][4B aes_size LE][4B xor_size LE][1B pad]
+ [AES-128-ECB 段（PKCS7，实际长度 = align16(aes_size) + 16 当 aes_size%16==0）]
+ [明文段] + [XOR 段（单字节循环）]
```

**密钥派生算法**（移植自社区工具 Bryan-Cyf/WeChatDaily，本机实测有效）：

```
xor_key = uin & 0xFF                      # 从 _t.dat 尾部投票推断（JPEG 尾 FFD9）
aes_key = MD5(str(uin) + wxid).hex()[:16] # ASCII 16 字节
账号目录名后 4 位 hex == md5(str(uin))[:4] # 约束 uin 枚举空间（2^24 ≈ 22 秒）
```

本机实例：uin=3702457409 → aes_key=`b2583f890a2db4f2`，xor=0x41。密钥缓存于 `data/media_keys.json`。

- **定位**：`msg/attach/MD5(wxid)/<YYYY-MM>/Img/*.dat`（第一层目录 = 会话 wxid 的 MD5）
- **文件级关联**：同目录候选按顺序分配（微信迁移后 mtime 不可靠，不能按时间匹配）

### 6.3 为什么图片要分 jpg 和 wxgf 两种文件

**微信 4.x 高清原图是私有 HEVC 编码（wxgf 格式）**。实测验证：

| 解码器 | 结果 |
|---|---|
| ffmpeg 8.1.2（软件 + QSV/CUVID 硬件） | ❌ `slice_qp_delta=-110` 超标准范围（-26~25），拒绝解码整帧 |
| libde265 1.1.1（VLC 同款） | ⚠️ 能出帧但 **U/V 色度平面全部丢失**（stdev≈0.3），输出绿色图 |
| 微信客户端 | ✅ 正常（使用私有解码器 VoipEngine.dll） |

**结论**：微信 HEVC 位流的色度是私有编码，标准解码器无法恢复。因此：
- **可查看版本**：微信标准缩略图（`_t.dat`，标准 jpg，颜色正确）
- **高清备份**：wxgf 原件解密保留（微信客户端可看，未来如有解码方案可升级）

### 6.4 并行化设计

- `analyze_all.py --parallel N`：线程池并行处理 N 个联系人
- **每线程独立 whisper 模型**：共享模型会因 GIL 串行化慢 ~3 倍（实测共享 67 条/分钟 vs 独立 106 条/分钟）
- 缓存文件锁（`_CACHE_FILE_LOCK`）：多实例并发写 `stt_cache.json` 不丢条目

---

## 7. 常见问题 FAQ

### Q1: 图片打不开 / 全是绿色

绿色 = wxgf 高清原图被错误解码（标准解码器色度不可恢复）。当前版本已修复：jpg 来自标准缩略图，颜色正确。若仍看到绿色 jpg，重跑导出（缩略图策略）或运行：

```bash
python scripts/convert_wxgf.py   # 批量重建图片（用缩略图）
```

### Q2: wxgf 文件是什么？能删吗？

wxgf = 微信私有 HEVC 高清原图。**可以删除**（jpg 缩略图足够日常查看），但删除后高清版丢失。微信客户端可正常查看 wxgf。

### Q3: 语音转写太慢

- 用 `--parallel 3`（3 路并行）
- 换小模型：settings.yaml `stt_model: "tiny"`（缓存跨模型复用，换回 small 不用重转）
- 检查缓存：`data/stt_cache.json` 存在且变大说明在缓存（第二次导出秒回）

### Q4: 模型下载失败（HuggingFace 网络问题）

faster-whisper 会自动从 hf-mirror.com 下载模型到 `data/models/`。若失败：
- 手动下载模型文件（config.json / model.bin / tokenizer.json / vocabulary.txt）放到 `data/models/faster-whisper-<模型>/`
- 模型仓库：`Systran/faster-whisper-<模型>`（hf-mirror.com 可用）

### Q5: 图片解密失败（[图片未解密] xxx.dat）

原因：对应图片未下载到本地（微信未加载过）或 .dat 损坏。原件保留不丢数据。可以打开微信让图片加载后再导出。

### Q6: 为什么聊天记录里有 [图片未解密] 而有的直接是 [图片]？

`[图片未解密]` = 解密失败保留 .dat 原件；`[图片]` = 正常导出（jpg 缩略图 + wxgf 备份）。

### Q7: 语音转写失败（显示 [语音] (时长 Xs)）

原因：VoiceInfo 无对应数据（早期语音格式）、SILK 解码失败、转写引擎异常。极少数（实测 2056 条中 3 条失败）。

### Q8: 导出很慢怎么办？

图片处理 + 语音转写是主要耗时。参考 [性能参考](#8-性能参考实测数据)，用并行 + tiny 模型 + 缓存。

---

## 8. 性能参考（实测数据）

本机（Windows 10, 微信 4.1.5.30, 数据量 3 人全量）：

| 项目 | 数值 |
|---|---|
| 语音总量（3 人） | Krista 2056 + Wileyond 1596 + GUA 1433 = 5085 条 |
| 转写成功率 | 99.85%（2053/2056） |
| 转写速度（3 线程独立 tiny 模型） | ~106 条/分钟 |
| 共享模型（GIL 串行） | ~67 条/分钟（不推荐） |
| 图片导出（3 人并行） | 4500+ 张，约 10~15 分钟 |
| 全流程 3 人并行（导出+媒体+分析+统计+时间线） | ~30 分钟 |
| 磁盘密钥派生耗时 | ~22 秒（首次，缓存后秒回） |
| 图片解密成功率 | 94.8%（1067/1125，其余为未下载/损坏） |

---

## 9. 维护与故障排查

### 关键文件

| 文件 | 作用 |
|---|---|
| `data/stt_cache.json` | 转写缓存（约 5000 条上限）。**删除 = 全部语音重新转写** |
| `data/media_keys.json` | 图片解密密钥缓存。删除后下次导出自动重新派生（~22s） |
| `data/models/faster-whisper-<模型>/` | whisper 模型文件。删除后自动重新下载 |
| `output/<联系人>/media/img/` | 导出图片 |

### 常见操作

```bash
# 批量重建图片（缩略图策略，chat.txt 引用自动更新）
python scripts/convert_wxgf.py

# 强制重新派生图片密钥（清缓存后导出）
del data\media_keys.json

# 查看转写缓存规模
python -c "import json; print(len(json.load(open('data/stt_cache.json'))))"
```

### 代码结构速查

```
src/miru/chat_analyzer/media/
├── voice.py        # VoiceInfo 提取 + pysilk 解码（SILK→PCM→WAV）
├── transcribe.py   # faster-whisper 封装 + 磁盘缓存（跨模型复用）
├── image.py        # .dat 定位/解密 + 缩略图提取 + 格式嗅探
├── v2key.py        # 磁盘密钥派生（uin 枚举）+ 内存扫描回退
├── processor.py    # 编排：MediaConfig / MediaProcessor / 渲染文本
└── models.py       # VoiceResult / ImageResult / MediaExportResult
```

---

## 附：本机实测结果存档（2026-08-09）

- Krista：34886 条消息，语音转写 **2053** 条，图片导出 **1124** 张（jpg/png）+ 955 wxgf 备份
- Wileyond：31898 条消息，语音转写 **1595** 条，图片导出 **1780** 张 + 1701 wxgf
- GUA：44133 条消息，语音转写 **1431** 条，图片导出 **1638** 张 + 1587 wxgf
- 转写示例：「我感觉我一出去他们就知道我现在还没有睡觉（时长 4s）」
- 图片密钥：uin=3702457409, aes=`b2583f890a2db4f2`, xor=0x41
