# 04 · Tool / Skill 系统（Q9 / Q12 / Q13）

## 1. 设计目标

- 一个工具 = 一个 Python 类 + JSON Schema，注册即生效，DeepSeek 自动可见、可调用
- 工具无权自行输出——只返回结构化结果，由 LLM 组织成自然语言
- 微信类工具默认**只读**、默认本地处理、可配置"结果是否允许送给 LLM"
- 与现有 V2 模块（chat_analyzer）直接复用，不重写

## 2. 核心抽象（server/miru_server/tools/base.py 已实现）

```python
@dataclass
class ToolContext:
    """每次调用注入的上下文：会话、数据库、配置、事件发射器"""
    session: "Session"                 # 当前对话（历史、persona 名）
    db: Session                        # SQLAlchemy 会话
    config: AppConfig
    emit: Callable[[str, dict], Awaitable[None]]   # 向手机发 WS 事件

class Tool(ABC):
    name: ClassVar[str]                        # 唯一名（送给 LLM 的函数名）
    description: ClassVar[str]                 # 中文描述：干什么、何时用
    parameters: ClassVar[dict]                 # JSON Schema（LLM 填参依据）
    require_confirm: ClassVar[bool] = False    # 高危工具需用户确认
    max_result_chars: ClassVar[int] = 8000     # 结果裁剪上限

    @abstractmethod
    async def run(self, ctx: ToolContext, **kwargs) -> ToolResult: ...

@dataclass
class ToolResult:
    ok: bool
    data: dict | list | str            # 序列化为 JSON 字符串回填给 LLM
    summary: str                       # 给人看的一句话状态（tool_end 事件）
```

注册表 `tools/registry.py`：启动时扫描 `builtin/` 下全部 `Tool` 子类 → `get_schemas()` 生成 OpenAI tools 数组 → `execute(name, args, ctx)` 带 30s 超时执行。**新增一个工具 = 新增一个文件**，无需改其他代码（未来支持外部插件目录，`tools_path` 配置项）。

## 3. 工具执行循环（core/pipeline.py）

```
用户输入
  → 发 LLM stream（附 tools schema）
  → 收到 finish_reason == "tool_calls"
      ├─ 逐个执行（并行调用则并发执行，结果按序回填）
      │    ├─ require_confirm → 暂停，发 user_action 等手机确认
      │    ├─ 发 tool_start 事件（手机显示状态）
      │    ├─ 超时 30s / 异常 → ToolResult(ok=False, 错误摘要)
      │    └─ 发 tool_end 事件
      ├─ messages.append(assistant: tool_calls) + append(tool: 各结果)
      └─ 再次 stream（上限 6 轮工具循环，防死循环烧钱）
  → 收到普通 finish → turn_end
```

**给 LLM 的工具使用规则（system prompt 内置）**：
- 用户闲聊时不要调用任何工具；工具结果用一两句话自然转述，不要照读数据
- 一次能把事做完就一次调完（支持并行调用）
- 微信工具结果里如果有隐私内容，回答时不要复述原文细节

## 4. 微信聊天分析接入（Q12）——复用现有 V2 模块

### 4.1 能力映射表（全部 import 复用，零重写）

| Miru 工具 | 复用的现有类/函数 | 数据来源 |
|-----------|-------------------|----------|
| `wechat_contact_list` | `OfflineWeChatDB.get_contacts()` | 离线库（无需微信运行） |
| `wechat_chat_stats` | `ChatStatistics` / `compute_statistics()` | 已导出 chat.txt 或按需离线导出 |
| `wechat_search_messages` | `OfflineWeChatDB.read_all_messages()` + 关键词过滤 | 离线库直读 |
| `wechat_recent_messages` | `ContactFullExporter`（时间窗口参数） | 离线导出 |
| `wechat_group_digest` | `ChatExporter.export()`（在线群）→ `DeepSeekClient.analyze_group` | 群消息（在线模式） |
| `wechat_export_images` | `ImageExtractor.export()`（V2 密钥，离线可解） | `attach/` 图片 |
| `wechat_transcribe_voice` | `VoiceExtractor` + `STTEngine`（本地 whisper） | `media_0.db` 语音消息 |
| `wechat_relationship_analysis` | 统计结果 + LLM 二次分析 | 组合 |

### 4.2 隐私分档（关键设计）

settings.yaml 里每个微信工具带 `llm_visibility` 档位：

| 档位 | 行为 | 用途 |
|------|------|------|
| `aggregates`（默认） | 只把**统计数字/摘要**给 LLM（条数、时间分布、词频 top10、字数） | 日常问答（"最近聊得多吗"） |
| `samples` | 统计 + 最多 N 条脱敏样例（去名字去链接） | 需要一点语境的判断 |
| `raw`（用户显式开启） | 原始消息文本 | 深度分析；**每轮前提示已开启** |

数据流：`微信库(PC本地) → 工具(本地读取) → 结果(按档位过滤) → DeepSeek → 自然语言`。原始聊天内容**默认不离开 PC**；用户说"帮我看看群里都在说什么"时，Miru 收到的是聚合结果而非原文。

### 4.3 接入方式

- 与 V2 共用同一 venv → `import miru.chat_analyzer` 直接可用；`try/except ImportError` 包裹 → 后端装到 Linux VPS 时该工具自动禁用（`tools.enabled` 列表里也不会有）。
- 复用 V2 的 `config/database_keys.yaml`、`config/settings.yaml → miru.wechat.data_dir` 等密钥与路径——**不另起炉灶**。
- 离线优先：`OfflineWeChatDB` 全家（联系人/消息/图片）不需要微信运行、不需要管理员权限；只有**群消息**依赖在线 `ChatExporter`（微信需登录运行）。

## 5. 图片 / 语音能力接入（Q13）

### 5.1 图片

两段式（与 V2 一致 + 新增理解层）：

1. **本地提取**（已有）：`ImageExtractor` 定位 `attach/` 下的 `.dat` → AES 解密（V2 磁盘派生密钥）→ 导出 jpg。
2. **内容理解**：文字模型 `deepseek-v4-flash` 不负责看图；图片统一交给 DeepSeek 多模态模型 `deepseek-v4-flash-vision-exp`。工具 `wechat_image_analysis` 会在本机解密后通过 Chat Completions 发送图片，返回描述，不上传原始文件到手机。
   - `image_find_and_export(contact, date)` → 导出到本地目录，返回文件清单（**图片不出 PC**）
   - `image_describe(paths)` → 仅对用户明确要求的图调 VLM，返回每张图的一句话描述 + 总括（LLM 二次总结）

### 5.2 语音消息

完全本地：`VoiceExtractor.get_voice_data()`（SILK V3）→ `decode_to_pcm` → 本地 whisper/SenseVoice 转写（V2 的 `STTEngine` 已有缓存机制 `stt_cache.json`）。工具：`wechat_transcribe_voice(contact, date)`。

### 5.3 未来扩展位

- `image_ocr`：接本地 PaddleOCR 或云 OCR（需求未提，留接口）
- 视频封面帧：`ffmpeg` 取帧后走 image_describe

## 6. 工具清单（MVP 起步集）

| 工具 | 权限 | llm_visibility | MVP 阶段 |
|------|------|----------------|----------|
| `get_current_time` | 公开 | — | 1 |
| `memory_set / memory_get / memory_list / memory_delete` | 公开 | — | 3 |
| `memory_search` | 公开 | — | 3 |
| `api_cost_report` / `api_budget_set` | 公开 | — | 7 |
| `wechat_contact_list` | 只读 | aggregates | 4 |
| `wechat_group_digest` | 只读 | aggregates | 4 |
| `wechat_chat_stats` | 只读 | aggregates | 5 |
| `wechat_search_messages` | 只读 | samples | 5 |
| `wechat_export_images` | 只读 | 本地 | 6 |
| `wechat_transcribe_voice` | 只读 | 本地 | 6 |
| `image_describe` | 需确认 | 按图 | 6 |
| `wechat_relationship_analysis` | 只读 | samples | 5+ |

每个工具的 `description` 写清楚"什么时候该用它"，这是决定 DeepSeek 调用质量的关键（示例见 `tools/builtin/wechat.py` 内注释）。

## 7. 工程护栏

- **结果裁剪**：`max_result_chars` 超限截断并加 `…(已截断，共 N 条)`，防单工具撑爆上下文
- **超时**：单工具 30s（微信离线导出大批量可能更久，可配置）；超时返回错误摘要
- **失败语义**：工具失败不中断对话——错误摘要交给 LLM，让它自然地说"现在读不到数据"
- **工具白名单**：settings `tools.enabled: [...]`，未启用的工具不出现在 LLM schema 里
- **成本护栏**：每轮工具循环 ≤6 次；工具结果总长 ≤32k 字符
