# 09 · MVP 路线图与云迁移（Q16 / Q20 / Q21）

## 1. MVP 定义与验收标准（Q20）

### MVP 1 —— 手机语音聊天闭环（本周可完成）

**范围**：
- FastAPI 后端 + WS 会话 + DeepSeek 流式 + 句级 TTS + 本地 STT（SenseVoice）+ VAD 断句
- 文字模式完全可用（终端 `ws_chat.py` 即可验证）
- 语音模式：按住说话 → 识别 → 流式回答 → 逐句播放 → 打断
- 多轮对话 + 会话落库 + 每轮费用入账

**验收**：在 PC 上 `voice_chat.py`（麦克风）跑通完整闭环；iPhone 连同一 Wi-Fi 用 Flutter MVP 页面跑通同样闭环。**延迟：说完 3 秒内开口。**

**暂不做**：工具调用、记忆、人格编辑、公网访问、UI 美化。

### MVP 2 —— Persona

范围：persona.yaml + system prompt 组装 + `GET/PUT /api/persona` + 手机端简单编辑页。
验收：改 yaml 重启后 Miru 语气明显变化；音色随 persona.voice 切换。

### MVP 3 —— Memory

范围：四类记忆表 + 自动提取后台任务 + memory_* 工具 + 手机端记忆查看/删除页。
验收："记住我每周三开会"→ 下次问"我周三有事吗"能答出来；多轮对话能引用之前说过的偏好。

### MVP 4 —— 微信群日报工具

范围：`wechat_group_digest` 工具（在线导出群消息 → 聚合摘要）+ tool 执行状态 UI。
验收："今天群里有什么值得看的？"→ Miru 调用工具 → 语音回报 3 个群要点。

### MVP 5 —— 聊天记录分析

范围：`wechat_chat_stats` / `wechat_search_messages` / `wechat_relationship_analysis`。
验收："我最近和 XX 聊天多吗？"→ 统计（条数/主动发起/时间分布）→ 自然语言结论。

### MVP 6 —— 图片与语音消息

范围：`wechat_export_images`（本地解密导出）+ `image_describe`（VLM）+ `wechat_transcribe_voice`。
验收："把昨天群里发的图片都整理出来"→ 导出 + 逐图一句话描述总结。

### MVP 7 —— API Cost Monitor

范围：成本面板（App 设置页折线图）+ 预算设置 + 超支提醒 + Miru 自答"这个月花了多少"。
验收：预算 150 元 → 用到 120 元时 Miru 主动在回答里提醒。

### MVP 8 —— 主动能力

范围：APScheduler 定时早报（复用 V1 日报资产）→ App 前台打开即收到；`server_note` 事件流。
验收：早上打开 App，Miru 播报"早，今天三件事：…"。**受自签 IPA 无推送限制**：靠 App 前台长连接，后台通知只能做到"打开即报"。

## 2. 扩展路径（Q21）

| 阶段 | 增量 | 依赖 |
|------|------|------|
| 0 骨架（本次交付） | WS 管线 + LLM 流式工具循环 + TTS/STT 接口 + 记忆/成本/DB + 测试 | 无 |
| 1-3 | 语音闭环 / Persona / Memory | 0 |
| 4-6 | 微信三件套（群日报/聊天分析/媒体） | 复用 V2 模块 |
| 7 | 成本面板 | 0 的账本已埋点 |
| 8 | 早报 + 主动提醒 | APScheduler（已有依赖） |
| 9 | 情绪化 TTS（LLM 标情绪标签逐句合成） | MiniMax emotion 参数 |
| 10 | 真·流式 STT（Paraformer 中间结果） | sherpa-onnx streaming 模型 |
| 11 | 云部署 + 微信工具节点分离 | §3 |
| 12 | 向量记忆检索、RAG 知识库 | bge-small-zh ONNX |

**原则**：每个 MVP 都是"用户可感知的能力增量"，不是内部重构；工具系统第 1 天就把扩展点留好，后续只是加文件。

## 3. 迁移到云服务器（Q16）——工具节点架构

### 3.1 问题

微信数据**必须留在家里 Windows PC**（微信登录在 PC 上），但后端要 7×24 在线 → 两者必须分离。

### 3.2 目标拓扑

```
iPhone ──wss://miru.yourdomain.com──▶ VPS（云后端：大脑/记忆/成本/TTS 调度）
                                         │
                                         │ 反向隧道（PC 主动连出，frp/WS 均可）
                                         ▼
                          家里 PC（工具节点：微信读取/本地STT/图片解密）
```

要点：
- **PC 主动向 VPS 连出**（frpc / 反向 WS），家里没有公网 IP、路由器不做端口映射也能通
- 工具注册表加 `location: "cloud" | "node-{name}"` 字段：LLM 调用微信工具时，云端把调用转发到节点执行，结果原路返回——**LLM 和手机端无感知**
- 手机到 VPS 走域名 + Let's Encrypt 证书，家庭宽带到期/断网只影响微信工具，不影响聊天
- VPS 规格：2C2G 足够（不跑 STT 时），约 ¥30-60/月；先把 STT 留在家 PC，省 VPS 内存

### 3.3 分步迁移

1. 后端 `docker compose` 化（Python 3.12 镜像，零代码改动）
2. VPS 部署后端 + PostgreSQL 替换 SQLite（改 `MIRU_DB_URL`）
3. 家 PC 装 frpc，隧道 `vps:7000 → localhost:8765`
4. 微信工具标记 `location: node-home`，走隧道协议执行
5. 手机把服务器地址从 ts.net 改成域名——完成

### 3.4 已为迁移埋好的伏笔

- 微信模块 import 全部 try/except 保护 → 云上装不了 pymem/pysilk 也能跑
- 工具执行接口天然是"参数进、JSON 出" → 加一层隧道协议即可远程化
- 配置全部 yaml + 环境变量 → 容器化零障碍
- SQLAlchemy 抽象 → 换库只改连接串
