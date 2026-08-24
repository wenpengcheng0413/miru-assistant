# 06 · 数据库与 API 设计（Q18 / Q19）

## 1. 数据库设计（Q18）——SQLite（SQLAlchemy 2.0）

单文件 `server/data/miru_server.db`，WAL 模式。个人单用户负载下毫秒级；迁云时换 PostgreSQL 只需改连接串（模型全用 ORM 定义，无原生方言 SQL）。

### 1.1 ER 关系

```
conversations 1─N messages 1─N tool_calls
conversations 1─N api_usage
budgets（按 月份+provider 唯一）
memory_profile / memory_preferences / memory_projects / memory_knowledge / memory_episodes（独立表）
```

### 1.2 DDL

```sql
CREATE TABLE conversations (
  id            TEXT PRIMARY KEY,          -- uuid4().hex
  title         TEXT DEFAULT '',
  persona       TEXT NOT NULL DEFAULT 'miru',
  created_at    DATETIME NOT NULL,
  updated_at    DATETIME NOT NULL
);

CREATE TABLE messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
  content         TEXT NOT NULL,
  created_at      DATETIME NOT NULL
);
CREATE INDEX idx_messages_conv ON messages(conversation_id, id);

CREATE TABLE tool_calls (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  args            TEXT NOT NULL,            -- JSON
  result          TEXT,                     -- JSON（按 llm_visibility 过滤后的）
  ok              INTEGER NOT NULL DEFAULT 0,
  duration_ms     INTEGER,
  created_at      DATETIME NOT NULL
);

CREATE TABLE api_usage (                    -- 成本账本（LLM/TTS/STT/VLM 全在这）
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
  provider        TEXT NOT NULL,            -- deepseek / minimax / dashscope / local
  model           TEXT NOT NULL,
  kind            TEXT NOT NULL,            -- llm / tts / stt / vlm
  input_tokens    INTEGER NOT NULL DEFAULT 0,
  output_tokens   INTEGER NOT NULL DEFAULT 0,
  cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
  chars           INTEGER NOT NULL DEFAULT 0,  -- TTS 按字符计费用
  requests        INTEGER NOT NULL DEFAULT 1,
  cost_rmb        REAL NOT NULL DEFAULT 0,
  peak            INTEGER NOT NULL DEFAULT 0,  -- 是否高峰时段计费
  meta            TEXT,                      -- 备注（会话轮次等）
  created_at      DATETIME NOT NULL
);
CREATE INDEX idx_usage_day ON api_usage(created_at);
CREATE INDEX idx_usage_provider ON api_usage(provider);

CREATE TABLE budgets (
  provider  TEXT NOT NULL,                  -- deepseek / minimax / total
  month     TEXT NOT NULL,                  -- 'YYYY-MM'
  limit_rmb REAL NOT NULL,
  PRIMARY KEY (provider, month)
);

CREATE TABLE memory_profile (
  key        TEXT PRIMARY KEY, value TEXT NOT NULL,
  source     TEXT NOT NULL DEFAULT 'auto',  -- auto / user
  updated_at DATETIME NOT NULL
);
CREATE TABLE memory_preferences (          -- 结构同上
  key TEXT PRIMARY KEY, value TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'auto', updated_at DATETIME NOT NULL
);
CREATE TABLE memory_projects (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  status     TEXT DEFAULT '',
  notes      TEXT DEFAULT '',
  updated_at DATETIME NOT NULL
);
CREATE TABLE memory_knowledge (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  content    TEXT NOT NULL,
  embedding  BLOB,                          -- 预留：bge-small-zh 向量（升级位）
  source     TEXT NOT NULL DEFAULT 'auto',
  created_at DATETIME NOT NULL
);
CREATE TABLE memory_episodes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
  summary         TEXT NOT NULL,
  created_at      DATETIME NOT NULL
);
```

## 2. REST API 设计（Q19）

前缀 `/api`，全部 `Authorization: Bearer <token>`。WS 协议见 [02 文档](02-流式管线与通信协议.md)。

### 2.1 健康与状态

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | `{status, stt_engine, tts_provider, llm_model, wechat_tools: bool}` |

### 2.2 会话与消息

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/conversations?limit=20` | 会话列表（标题/时间） |
| GET | `/api/conversations/{id}/messages` | 消息历史 |
| DELETE | `/api/conversations/{id}` | 删除会话（级联删消息/工具记录） |

### 2.3 记忆

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memory?scope=profile\|preferences\|projects\|knowledge\|episodes` | 列出（手机端记忆管理页） |
| PUT | `/api/memory/{scope}/{key}` | `{value}` 写入/更新（source=user） |
| DELETE | `/api/memory/{scope}/{key}` | 删除 |
| GET | `/api/memory/search?q=…` | 关键词检索 |

### 2.4 Persona

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/persona?name=miru` | 当前人设 |
| PUT | `/api/persona` | 整份 yaml 覆盖保存（手机端编辑界面用） |
| GET | `/api/persona/list` | 可用人设清单 |

### 2.5 成本

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/cost/report?days=7\|30&month=YYYY-MM` | 按天/按月汇总：token、次数、费用、按模型/按 provider 分桶 |
| GET | `/api/cost/budget` | 各 provider 预算与当前使用 |
| PUT | `/api/cost/budget` | `{provider, month, limit_rmb}` |

### 2.6 调试端点（开发期用，也可被 App 设置页复用）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/debug/tts` | `{text}` → 音频（测 TTS 链路） |
| POST | `/api/debug/stt` | multipart 上传 wav → `{text}`（测 STT 链路） |
| GET | `/api/tools` | 已注册工具清单与 schema |

### 2.7 示例

```bash
curl -H "Authorization: Bearer $MIRU_SERVER_TOKEN" http://127.0.0.1:8765/api/cost/report?days=7
# {"total_rmb": 3.42, "by_provider": {"deepseek": 3.01, "minimax": 0.41},
#  "by_day": [{"date":"2026-08-12","rmb":0.53}, ...]}

curl -X PUT -H "Authorization: Bearer $MIRU_SERVER_TOKEN" \
     -d '{"provider":"deepseek","month":"2026-08","limit_rmb":150}' \
     http://127.0.0.1:8765/api/cost/budget
```

## 3. 迁移策略

- MVP 用 SQLAlchemy `Base.metadata.create_all()` 直接建表；引入新字段时手写小迁移脚本 `db/migrate_00x.py`（按序号执行并记录在 `schema_migrations` 表）
- 迁 PostgreSQL 时：改 `MIRU_DB_URL` 环境变量 + `pip install psycopg[binary]`，其余零改动（VPS 部署场景，见 09 文档）
