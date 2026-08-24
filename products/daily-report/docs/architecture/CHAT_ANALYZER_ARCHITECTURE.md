# Miru v2 — Chat Analyzer Architecture Design

> **Design Principle**: All Miru v2 capabilities are built on Miru v1.1, but must NOT affect the stable Daily Report system.

---

## 1. Current Project Architecture (Miru v1.1)

### 1.1 Entry Points

| Entry | Path | Trigger | Purpose |
|-------|------|---------|---------|
| Windows Task Scheduler | `scripts/run_daily.bat` → `scripts/run_daily.py` | Daily 22:00 | Production daily run |
| Bootstrap | `src/miru/bootstrap.py` | Automated | Pre-flight checks → Pipeline |
| CLI | `src/miru/cli/main.py` | Manual | `miru run/status/config/decrypt/...` |

### 1.2 Module Map

```
src/miru/
├── __init__.py              # __version__ = "1.0.0"
├── bootstrap.py             # Automated entry (Task Scheduler)
├── core/
│   ├── pipeline.py          # MiruPipeline — 6-step orchestration
│   ├── context.py           # PipelineContext dataclass
│   ├── logging.py           # Loguru initialization
│   └── exit_codes.py        # Exit code classification
├── cli/
│   └── main.py              # Typer CLI (8 commands)
├── collector/
│   ├── diagnostics.py       # WeChat environment detection
│   ├── wechat_db_decrypt.py # SQLCipher key extraction + decryption
│   └── wechat_reader.py     # WeChatDBReader — reads messages from DB
├── filter/
│   ├── __init__.py          # Re-exports: process, build_llm_context
│   ├── models.py            # CleanMessage, FilterResult
│   ├── pipeline.py          # Filter pipeline (dedup→clean→classify→group)
│   ├── dedup.py             # Deduplication by server_id
│   ├── cleaner.py           # Message cleaning (system/empty/short)
│   ├── classifier.py        # Rule-based pre-classification
│   └── group_filter.py      # Group by group_name
├── llm/
│   ├── __init__.py
│   ├── client.py            # DeepSeekClient (OpenAI SDK compatible)
│   └── schemas.py           # Pydantic: GroupAnalysis, LLMCallResult, TokenUsage
├── report/
│   ├── __init__.py
│   ├── generator.py         # ReportGenerator (merge + render + persist)
│   └── formatter.py         # Truncation helpers
├── storage/
│   ├── __init__.py
│   ├── database.py          # Database (SQLite connection manager, WAL mode)
│   ├── models.py            # Dataclasses: ChatGroup, RawMessage, DailyReport, etc.
│   ├── repository.py        # Repository layer (GroupRepo, MessageRepo, ReportRepo, etc.)
│   ├── migrations.py        # Schema migrations
│   └── backup.py            # Database backup
├── notify/
│   ├── __init__.py
│   ├── base.py              # BaseNotifier abstract class
│   ├── console.py           # ConsoleNotifier
│   ├── pushplus.py          # PushPlusNotifier (HTTP POST)
│   └── dispatcher.py        # dispatch_report(), retry_failed_pushes()
├── scheduler/
│   └── scheduler.py         # Health check, failure notification
└── utils/
    ├── __init__.py
    ├── config.py            # AppConfig, load_config (Pydantic + YAML)
    ├── logger.py            # Legacy logger setup (not used by core)
    └── errors.py            # Custom exception classes
```

### 1.3 Daily Report Pipeline Flow

```
Step 1: Environment Check
    ├── detect_wechat_process()    → PID, version
    ├── find_wechat_data_dir()     → data directory path
    └── Admin permission check

Step 2: Message Collection
    ├── extract_keys_from_process()  → memory scan for SQLCipher keys
    ├── try_decrypt_wechat_db()      → contact.db + message_0.db
    ├── WeChatDBReader               → read groups, read messages
    └── Time range: today 00:00 ~ now

Step 3: Message Filter
    ├── deduplicate()            → by server_id (cross-run via DB)
    ├── clean()                  → remove system/empty/short/non-text
    ├── classify_all()           → rule-based pre-classification
    └── group_by_group_name()    → {group_name: [CleanMessage]}

Step 4: LLM Analysis
    ├── build_llm_context()      → format messages as text
    ├── DeepSeekClient.analyze_groups()  → sequential per-group analysis
    └── Retry: token budget / empty response / JSON parse

Step 5: Report Generation
    ├── ReportGenerator.generate()  → merge + render + persist
    ├── Jinja2 template: daily.md.j2
    └── Save to SQLite: daily_reports + report_items

Step 6: Push Notification
    ├── PushPlusNotifier.send()
    └── ConsoleNotifier.send() (dry-run)
```

---

## 2. Module Reusability Analysis

### 2.1 ✅ Directly Reusable (No Changes Needed)

| Module | File | Why |
|--------|------|-----|
| WeChat DB Reader | `collector/wechat_reader.py` | `WeChatDBReader` already supports reading messages by any username (not just @chatroom). Has `get_contacts()`, `get_messages(username, start, end)`. Chat Analyzer uses private chats — same API. |
| DB Decrypt | `collector/wechat_db_decrypt.py` | `extract_keys_from_process()`, `try_decrypt_wechat_db()` work for any WeChat DB. Chat Analyzer uses the same message_0.db. |
| Diagnostics | `collector/diagnostics.py` | `detect_wechat_process()`, `find_wechat_data_dir()` are environment-level, not Daily Report-specific. |
| Logger | `core/logging.py` | `init_logging()`, `set_run_id()` are general-purpose. Chat Analyzer can call `init_logging()` at startup. |
| Config Loader | `utils/config.py` | `load_config()` is general-purpose. Chat Analyzer can add its own config section (e.g., `chat:`) without modifying existing sections. |
| Database | `storage/database.py` | `Database` class is a generic SQLite connection manager. Chat Analyzer can use a separate DB file or add tables. |
| Errors | `utils/errors.py` | Custom exceptions are general-purpose. |

### 2.2 ✅ Reusable with Minor Extensions (Add Parameters, Don't Change Existing)

| Module | File | Extension Needed |
|--------|------|------------------|
| DeepSeek Client | `llm/client.py` | Add a generic `chat()` method that accepts custom system/user prompts. The existing `analyze_group()` stays untouched. Add `analyze_chat()` for chat analysis with different prompt template. |
| LLM Schemas | `llm/schemas.py` | Add new Pydantic models for chat analysis output (e.g., `ChatAnalysis`). Existing models untouched. |
| CleanMessage | `filter/models.py` | Can be reused as-is for chat export. Chat messages are simpler — no group context needed. |
| Config Models | `utils/config.py` | Add `ChatConfig` model. Existing `AppConfig` gets a new optional `chat: ChatConfig` field. |

### 2.3 ❌ Cannot/Should Not Be Reused

| Module | File | Why Not |
|--------|------|---------|
| Pipeline | `core/pipeline.py` | `MiruPipeline` is hardcoded for the 6-step Daily Report flow. Chat Analyzer has a completely different flow. |
| Pipeline Context | `core/context.py` | `PipelineContext` tracks Daily Report state (groups_collected, llm_token_usage, push_status). Not relevant. |
| Filter Pipeline | `filter/pipeline.py` | `process()` is designed for batch group chat filtering → LLM. Chat Analyzer exports raw messages, then optionally analyzes. |
| Filter Components | `filter/cleaner.py`, `classifier.py`, `dedup.py`, `group_filter.py` | Designed for group chat → Daily Report. Chat Analyzer exports everything unfiltered. |
| Report Generator | `report/generator.py` | `ReportGenerator` renders Daily Report Markdown with urgent/deadline/notice sections. Chat Analyzer uses different templates. |
| Notify | `notify/*` | Chat Analyzer is a CLI tool that outputs to local files. No push needed. |
| Scheduler | `scheduler/*` | Chat Analyzer is not a scheduled task. |
| Bootstrap | `bootstrap.py` | Bootstrap is the Daily Report entry with pre-flight checks. Chat Analyzer uses its own CLI entry. |

---

## 3. Chat Analyzer Architecture Design

### 3.1 Core Principle: Independent Module, Shared Foundation

```
┌─────────────────────────────────────────────────────────────┐
│                      Miru v2                                 │
├─────────────────────────┬───────────────────────────────────┤
│   Daily Report (v1.1)   │   Chat Analyzer (v2)              │
│   ===================   │   ====================             │
│   scripts/run_daily.bat │   python -m miru.chat.cli \       │
│   Windows Task Scheduler│       --contact "张三"             │
│                         │                                   │
│   core/pipeline.py      │   miru/chat/                      │
│   filter/*              │   ├── cli.py                      │
│   report/*              │   ├── exporter.py                 │
│   notify/*              │   ├── analyzer.py                 │
│   scheduler/*           │   ├── voice.py                    │
│   core/context.py       │   ├── ocr.py                      │
│                         │   ├── timeline.py                 │
│                         │   ├── statistics.py               │
│                         │   └── file_parser.py              │
├─────────────────────────┴───────────────────────────────────┤
│              Shared Foundation (v1.1 — NO CHANGES)           │
│   =======================================================   │
│   collector/wechat_reader.py    ← WeChatDBReader             │
│   collector/wechat_db_decrypt.py ← Key extraction + decrypt  │
│   collector/diagnostics.py      ← Environment detection      │
│   llm/client.py                 ← DeepSeekClient (+ new method) │
│   llm/schemas.py                ← Pydantic models (+ new)    │
│   utils/config.py               ← Config (+ chat section)    │
│   core/logging.py               ← Loguru init                │
│   storage/database.py           ← SQLite connection          │
│   utils/errors.py               ← Custom exceptions          │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Chat Analyzer Flow

```
Step 1: Find Contact
    Input: --contact "张三"
    ├── WeChatDBReader.get_contacts()  → list of all contacts
    ├── Fuzzy match by nickname/remark/alias
    └── Resolve to wechat username

Step 2: Read Messages
    ├── WeChatDBReader.get_messages(username, start, end)
    ├── Time range: --start "2024-01-01" --end "2024-12-31"
    └── Default: all available messages

Step 3: Sort & Export TXT
    ├── Sort by create_time ASC
    ├── Format: [YYYY-MM-DD HH:MM] Sender: Content
    └── Save: output/{contact_name}/chat.txt

Step 4: Export Voice (Phase 5)
    ├── Filter local_type=34 (voice messages)
    ├── Extract voice files from WeChat media storage
    └── Save: output/{contact_name}/voice/*.silk

Step 5: Whisper Transcription (Phase 5)
    ├── Convert silk → wav (silk-v3-decoder or ffmpeg)
    └── Whisper STT → text transcript

Step 6: Generate Full Chat Record
    ├── Merge text + voice transcripts
    ├── Sort by time
    └── Save: output/{contact_name}/chat_full.txt

Step 7: DeepSeek Analysis (Phase 2)
    ├── Build prompt with full chat context
    ├── DeepSeekClient.analyze_chat()
    └── Generate: output/{contact_name}/analysis.md

Step 8: Statistics (Phase 3)
    ├── Message frequency by day/hour
    ├── Response time analysis
    ├── Word count stats
    └── Save: output/{contact_name}/statistics.json

Step 9: Timeline (Phase 4)
    ├── Key events detection
    ├── Relationship milestones
    └── Save: output/{contact_name}/timeline.md
```

### 3.3 Output Directory Structure

```
output/
└── {contact_display_name}/
    ├── chat.txt              # Raw text export
    ├── chat_full.txt         # Text + voice transcripts (Phase 5)
    ├── analysis.md           # AI analysis report (Phase 2)
    ├── statistics.json       # Chat statistics (Phase 3)
    ├── timeline.md           # Event timeline (Phase 4)
    ├── voice/                # Exported voice files (Phase 5)
    │   ├── 20240601_143022.silk
    │   └── 20240601_143022.wav
    ├── transcript/           # Whisper output (Phase 5)
    │   ├── 20240601_143022.txt
    │   └── transcript_full.txt
    ├── images/               # Exported images (Phase 6)
    │   └── 20240601_150000.jpg
    └── files/                # Exported documents (Phase 7)
        └── 20240615_meeting.pdf
```

---

## 4. Recommended Directory Structure

```
src/miru/
├── __init__.py                  # Version bump: "2.0.0"
│
├── chat/                        # ★ NEW: Chat Analyzer module
│   ├── __init__.py
│   ├── cli.py                   # Typer CLI entry for chat commands
│   ├── exporter.py              # Message export → TXT
│   ├── analyzer.py              # DeepSeek chat analysis
│   ├── statistics.py            # Chat statistics engine
│   ├── timeline.py              # Event timeline generator
│   ├── voice.py                 # Voice message export (Phase 5)
│   ├── transcriber.py           # Whisper STT integration (Phase 5)
│   ├── ocr.py                   # Image OCR (Phase 6)
│   ├── file_parser.py           # PDF/Word/Excel parsing (Phase 7)
│   ├── merger.py                # Merge text + voice into full record
│   ├── contact_resolver.py      # Name → Username resolution
│   └── models.py                # Chat-specific data models
│
├── core/                        # (NO CHANGES)
│   ├── pipeline.py              # Daily Report — untouched
│   ├── context.py               # Daily Report — untouched
│   ├── logging.py               # Shared — untouched
│   └── exit_codes.py            # Shared — untouched
│
├── collector/                   # (NO CHANGES)
│   ├── wechat_reader.py         # Shared — untouched
│   ├── wechat_db_decrypt.py     # Shared — untouched
│   └── diagnostics.py           # Shared — untouched
│
├── llm/                         # (MINOR ADDITIONS)
│   ├── client.py                # + analyze_chat() method
│   └── schemas.py               # + ChatAnalysis, ChatMessage models
│
├── utils/                       # (MINOR ADDITIONS)
│   ├── config.py                # + ChatConfig section
│   └── ...
│
├── filter/                      # (NO CHANGES)
├── report/                      # (NO CHANGES)
├── storage/                     # (NO CHANGES — chat uses file output, not DB)
├── notify/                      # (NO CHANGES)
├── scheduler/                   # (NO CHANGES)
└── cli/                         # (EXTEND: register chat subcommands)
    └── main.py                  # + chat command group

tests/
├── unit/
│   ├── test_chat_exporter.py    # ★ NEW
│   ├── test_chat_analyzer.py    # ★ NEW
│   ├── test_chat_statistics.py  # ★ NEW
│   ├── test_contact_resolver.py # ★ NEW
│   └── ... (existing tests untouched)
└── integration/
    └── test_chat_flow.py        # ★ NEW

scripts/
├── run_daily.bat                # (NO CHANGES)
├── run_daily.py                 # (NO CHANGES)
└── chat_analyzer.py             # ★ NEW: convenience wrapper

config/
├── settings.yaml                # (EXTEND: add chat: section)
└── settings.example.yaml        # (EXTEND: add chat: section example)

output/                          # ★ NEW: Chat Analyzer output directory
└── .gitkeep

docs/
└── CHAT_ANALYZER_ARCHITECTURE.md  # This document
```

---

## 5. Module Responsibilities

### 5.1 `miru/chat/cli.py` — CLI Entry

```python
# Commands:
miru chat export --contact "张三" [--start 2024-01-01] [--end 2024-12-31]
miru chat analyze --contact "张三" [--start YYYY-MM-DD] [--end YYYY-MM-DD]
miru chat full --contact "张三" [--start YYYY-MM-DD] [--end YYYY-MM-DD]  # export + analyze + stats
miru chat list-contacts  # List all WeChat contacts (not just groups)
miru chat voice --contact "张三"    # Phase 5
miru chat transcribe --contact "张三"  # Phase 5
```

**Dependencies**: `exporter`, `analyzer`, `contact_resolver`, `core/logging`  
**Does NOT touch**: `core/pipeline`, `filter/`, `report/`, `notify/`

### 5.2 `miru/chat/contact_resolver.py` — Contact Resolution

Finds a contact by display name (nickname/remark/alias) via fuzzy matching.

**Input**: `"张三"` (display name)  
**Output**: `WeChatContact` with resolved `username`  
**Uses**: `WeChatDBReader.get_contacts()` from `collector/wechat_reader.py`

### 5.3 `miru/chat/exporter.py` — Message Exporter

Reads all messages for a contact, sorts by time, formats, writes TXT.

**Input**: contact username, time range  
**Output**: `chat.txt` file in output directory  
**Uses**: `WeChatDBReader.get_messages()` from `collector/wechat_reader.py`

### 5.4 `miru/chat/analyzer.py` — AI Analysis

Invokes DeepSeek to analyze chat history and produce insights.

**Input**: chat text, contact name  
**Output**: `analysis.md` file  
**Uses**: `DeepSeekClient` with chat-specific prompts  
**Prompt differences from Daily Report**:
- System prompt: "You are a relationship analyst..." instead of "学习助手"
- Focus: communication patterns, relationship dynamics, key topics, emotional tone
- Not: urgent tasks, deadlines, notices

### 5.5 `miru/chat/statistics.py` — Chat Statistics

Computes quantitative metrics from chat data.

**Metrics**:
- Message count by day/week/month
- Message count by hour (activity patterns)
- Average message length
- Response time distribution
- Word frequency analysis
- Initiation ratio (who starts conversations more)
- Emoji/sticker usage stats

**Output**: `statistics.json`

### 5.6 `miru/chat/timeline.py` — Event Timeline

Identifies key events and milestones from chat history.

**Events**: first contact, key conversations, shared media, important dates

**Output**: `timeline.md`

### 5.7 `miru/chat/voice.py` — Voice Export (Phase 5)

Extracts voice messages (local_type=34) from WeChat media storage.

**Input**: contact, time range  
**Output**: `voice/*.silk` files  
**Challenge**: WeChat stores media files separately from the message DB

### 5.8 `miru/chat/transcriber.py` — Whisper STT (Phase 5)

Converts voice to text using Whisper.

**Input**: `voice/*.wav` files  
**Output**: `transcript/*.txt` files  
**Dependency**: `openai-whisper` or `faster-whisper`

### 5.9 `miru/chat/ocr.py` — Image OCR (Phase 6)

Extracts text from shared images.

**Input**: images from chat  
**Output**: OCR text appended to chat record  
**Dependency**: `paddleocr` or `tesseract`

### 5.10 `miru/chat/file_parser.py` — File Parsing (Phase 7)

Parses shared documents (PDF, Word, Excel).

**Input**: document files  
**Output**: extracted text  
**Dependencies**: `PyPDF2`, `python-docx`, `openpyxl`

### 5.11 `miru/chat/models.py` — Data Models

```python
@dataclass
class ChatExportConfig:
    contact_name: str
    start_date: Optional[str]
    end_date: Optional[str]
    output_dir: str
    include_voice: bool = False
    include_images: bool = False

@dataclass
class ChatStatistics:
    total_messages: int
    messages_by_day: dict[str, int]
    messages_by_hour: dict[int, int]
    avg_message_length: float
    response_times: list[float]
    word_frequency: dict[str, int]
    sent_by_me: int
    sent_by_them: int

@dataclass
class ChatAnalysisResult:
    contact_name: str
    period: str
    summary: str
    key_topics: list[str]
    communication_style: str
    relationship_insights: str
    emotional_tone: str
    notable_events: list[str]
```

### 5.12 `miru/chat/merger.py` — Record Merger

Merges text messages with voice transcripts into a unified chronological record.

---

## 6. Extension Points

### 6.1 Plugin Architecture (Future)

```python
# src/miru/chat/base.py
class ChatProcessor(ABC):
    """Base class for all chat processing modules."""
    
    @abstractmethod
    def process(self, messages: list[WeChatMessage], output_dir: Path) -> Any:
        ...

# Each processor implements this:
class VoiceExporter(ChatProcessor): ...
class WhisperTranscriber(ChatProcessor): ...
class OCRExtractor(ChatProcessor): ...
class FileParser(ChatProcessor): ...
class EmotionAnalyzer(ChatProcessor): ...  # Future
class RelationshipTimeline(ChatProcessor): ...  # Future
```

### 6.2 Future Extensions (Beyond Phase 7)

| Extension | Description | Processor |
|-----------|-------------|-----------|
| Emotion Analysis | Sentiment analysis on messages | `emotion.py` |
| Relationship Timeline | Visual timeline of relationship phases | `relationship.py` |
| Topic Modeling | LDA/BERTopic for conversation themes | `topics.py` |
| Network Graph | Social network from group chats | `network.py` |
| Multi-language | Translation support | `translate.py` |
| Search | Full-text search across all chats | `search.py` |
| Export Formats | JSON, HTML, PDF export | `exporters/` |

---

## 7. Production Safety Analysis

### 7.1 Production System Checklist

| System Component | File(s) | Impact Assessment |
|-----------------|---------|-------------------|
| `scripts/run_daily.bat` | `scripts/run_daily.bat` | ✅ ZERO — not modified |
| Windows Task Scheduler | N/A (Windows config) | ✅ ZERO — unchanged |
| Pipeline | `core/pipeline.py` | ✅ ZERO — not touched |
| Pipeline Context | `core/context.py` | ✅ ZERO — not touched |
| Filter Pipeline | `filter/pipeline.py` | ✅ ZERO — not touched |
| Report Generator | `report/generator.py` | ✅ ZERO — not touched |
| Push (PushPlus) | `notify/pushplus.py` | ✅ ZERO — not touched |
| Retry Logic | `llm/client.py` | ✅ ZERO — new method added, existing `analyze_group()` untouched |
| Database Schema | `storage/migrations.py` | ✅ ZERO — no new tables needed (Chat Analyzer uses file output) |
| Database Connection | `storage/database.py` | ✅ ZERO — Chat Analyzer doesn't use it |
| Replay Mode | `core/pipeline.py` (replay_date param) | ✅ ZERO — not touched |
| Config | `utils/config.py` | ⚠️ MINOR — add optional `chat:` section, existing sections unchanged |
| WeChat DB Reader | `collector/wechat_reader.py` | ✅ ZERO — used as-is, no modifications |
| DB Decrypt | `collector/wechat_db_decrypt.py` | ✅ ZERO — used as-is |
| Logger | `core/logging.py` | ✅ ZERO — used as-is |
| Bootstrap | `bootstrap.py` | ✅ ZERO — not touched |
| CLI | `cli/main.py` | ⚠️ MINOR — register new `chat` command group, existing commands untouched |

### 7.2 Risk Mitigation Strategies

#### Risk 1: Config File Changes Break Daily Report
**Mitigation**: Add `chat` as an entirely optional section in `settings.yaml`. If the section is missing, Chat Analyzer uses defaults. Daily Report never reads the `chat` section. Backward compatible by design.

```yaml
# config/settings.yaml
miru:  # Existing — unchanged
  groups: [...]
  llm: {...}
  ...

chat:  # NEW — completely optional, ignored by Daily Report
  output_dir: "output"
  llm:
    model: "deepseek-v4-flash"
  default_contact: ""
```

#### Risk 2: DeepSeekClient Changes Break Daily Report LLM Calls
**Mitigation**: Add `analyze_chat()` as a NEW method. The existing `analyze_group()` method is NOT modified. The client is instantiated separately for Chat Analyzer with its own config.

#### Risk 3: WeChatDBReader Gets Modified
**Mitigation**: WeChatDBReader is used **as-is**. Chat Analyzer calls the same `get_messages()` API with a contact username instead of a group username. No changes needed — the reader already supports this.

#### Risk 4: Python Import Side Effects
**Mitigation**: Chat Analyzer modules live in `miru/chat/` — a separate package. Importing `miru.chat.exporter` does NOT import `miru.core.pipeline` or any Daily Report module.

#### Risk 5: Dependency Conflicts
**Mitigation**: Phase 5-7 dependencies (whisper, paddleocr, PyPDF2, etc.) are optional. The Chat Analyzer CLI checks for their availability at runtime and provides clear "install with: pip install miru[voice]" messages.

---

## 8. Development Roadmap

### Phase 1 — Contact Chat Export (Text Only)

**Goal**: `miru chat export --contact "张三"` produces `output/张三/chat.txt`

**New Files**:
- `src/miru/chat/__init__.py`
- `src/miru/chat/cli.py`
- `src/miru/chat/exporter.py`
- `src/miru/chat/contact_resolver.py`
- `src/miru/chat/models.py`
- `scripts/chat_analyzer.py` (convenience wrapper)

**Modified Files**:
- `src/miru/cli/main.py` — register `chat` command group (add ~3 lines)
- `src/miru/utils/config.py` — add `ChatConfig` model (add ~15 lines, optional)
- `src/miru/__init__.py` — bump version to "2.0.0-dev"

**Impact Assessment**:
| System | Impact |
|--------|--------|
| Daily Report | ✅ NONE |
| Pipeline | ✅ NONE |
| Database | ✅ NONE |
| Replay | ✅ NONE |
| PushPlus | ✅ NONE |
| Retry | ✅ NONE |

**Risk Level**: 🟢 **LOW** — New code only, no existing logic changed.

**Tests Needed**: `test_chat_exporter.py`, `test_contact_resolver.py`

---

### Phase 2 — AI Analysis

**Goal**: `miru chat analyze --contact "张三"` produces `output/张三/analysis.md`

**New Files**:
- `src/miru/chat/analyzer.py`
- `src/miru/llm/prompts/chat_analysis.j2` (new Jinja2 template)

**Modified Files**:
- `src/miru/llm/client.py` — add `analyze_chat()` method (new, ~50 lines)
- `src/miru/llm/schemas.py` — add `ChatAnalysis` Pydantic model (~30 lines)

**Impact Assessment**:
| System | Impact |
|--------|--------|
| Daily Report | ✅ NONE — `analyze_group()` unchanged |
| Pipeline | ✅ NONE |
| LLM | ⚠️ Additive — new method on DeepSeekClient, existing methods untouched |
| Retry | ✅ NONE — retry logic is per-method |

**Risk Level**: 🟢 **LOW** — Additive changes to LLM client only.

**Tests Needed**: `test_chat_analyzer.py`

---

### Phase 3 — Chat Statistics

**Goal**: `miru chat stats --contact "张三"` produces `output/张三/statistics.json`

**New Files**:
- `src/miru/chat/statistics.py`

**Modified Files**: None (stats runs on exported chat.txt)

**Impact Assessment**: All systems ✅ NONE

**Risk Level**: 🟢 **LOW** — Pure computation, reads text file.

**Tests Needed**: `test_chat_statistics.py`

---

### Phase 4 — Event Timeline

**Goal**: `miru chat timeline --contact "张三"` produces `output/张三/timeline.md`

**New Files**:
- `src/miru/chat/timeline.py`

**Modified Files**: None

**Impact Assessment**: All systems ✅ NONE

**Risk Level**: 🟢 **LOW**

---

### Phase 5 — Voice Export + Whisper Transcription

**Goal**: Export voice messages, transcribe with Whisper

**New Files**:
- `src/miru/chat/voice.py`
- `src/miru/chat/transcriber.py`
- `src/miru/chat/merger.py`

**Modified Files**: None

**New Dependencies**: `openai-whisper` or `faster-whisper`, `silk-v3-decoder` or `ffmpeg`

**Impact Assessment**:
| System | Impact |
|--------|--------|
| Daily Report | ✅ NONE |
| Dependencies | ⚠️ New optional deps — use extras: `pip install miru[voice]` |

**Risk Level**: 🟡 **MEDIUM** — New external dependencies. Voice file extraction requires understanding WeChat media storage format.

---

### Phase 6 — Image OCR

**Goal**: Extract text from shared images

**New Files**:
- `src/miru/chat/ocr.py`

**New Dependencies**: `paddleocr` or `pytesseract`

**Risk Level**: 🟡 **MEDIUM** — OCR accuracy varies.

---

### Phase 7 — File Parsing (PDF/Word/Excel)

**Goal**: Extract text from shared documents

**New Files**:
- `src/miru/chat/file_parser.py`

**New Dependencies**: `PyPDF2`, `python-docx`, `openpyxl`

**Risk Level**: 🟡 **MEDIUM** — File format compatibility issues.

---

### Phase 8 — Unified CLI + `miru chat full`

**Goal**: `miru chat full --contact "张三"` runs all phases at once.

**New Files**: None (orchestration logic in `cli.py`)

**Risk Level**: 🟢 **LOW**

---

## 9. Architecture Review

### Scoring (1-5, 5 = Best)

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| **Maintainability** | ⭐⭐⭐⭐⭐ | New module is self-contained in `miru/chat/`. Each processor is a single file with a single responsibility. No cross-dependencies with Daily Report code. Changes to Chat Analyzer can never break Daily Report. |
| **Extensibility** | ⭐⭐⭐⭐⭐ | Plugin architecture via `ChatProcessor` base class. Adding Voice/OCR/PDF/Emotion is a new file implementing `process()`. CLI can auto-discover processors. Configuration-driven. |
| **Reusability** | ⭐⭐⭐⭐☆ | Reuses 8 core modules from v1.1 without modification. `WeChatDBReader`, `DeepSeekClient`, config, logging, diagnostics all shared. LLM client gets a new method (additive, not breaking). Config gets a new optional section. One point off because `llm/client.py` needs a new method — ideally this would be fully independent. |
| **Long-term Maintenance** | ⭐⭐⭐⭐⭐ | Clear separation: Daily Report = automated batch, Chat Analyzer = interactive CLI. Different code paths, different output. If one breaks, the other is unaffected. Both share the same foundation, so foundation fixes benefit both. No code duplication — shared modules are truly shared, not copied. |
| **Production Safety** | ⭐⭐⭐⭐⭐ | Zero modifications to production code paths. `scripts/run_daily.bat`, `MiruPipeline`, filter pipeline, report generator, push — all untouched. New code lives in a new package. Existing tests continue to pass. Config changes are additive and optional. |

### Overall Assessment

**The design meets the prime directive: Miru v2 builds on Miru v1.1 without risking the Daily Report system.**

The key architectural decisions that ensure this:

1. **New package, not refactored code** — Chat Analyzer is `miru/chat/`, completely separate from the Daily Report's `core/`, `filter/`, `report/` modules.

2. **Shared foundation, not shared pipeline** — The shared modules (reader, decrypt, client, config, logging) are infrastructure, not business logic. They don't encode Daily Report assumptions.

3. **Additive, not transformative** — Where existing modules need extension (LLM client, config), changes are strictly additive: new methods, new optional fields. Existing signatures and behavior are preserved.

4. **File output, not database** — Chat Analyzer outputs to files in `output/`, not to the Daily Report's SQLite database. Zero schema conflicts.

5. **Separate CLI namespace** — `miru chat ...` vs `miru run`. Different Typer command groups. No argument conflicts.
