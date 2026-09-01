# Phase 9 免费优先 STT/TTS 实施与生产激活记录

日期：2026-09-02

状态：腾讯云 STT、家庭节点回退、免费 Cloud TTS、生产部署和自动化验收已完成；iPhone 语音闭环真机验收待完成。

## 当前结论

生产环境已启用 `stt.engine: tencent`。腾讯云“一句话识别”是 Cloud 主 Provider，可在电脑关闭时工作；调用失败、不可用或免费额度耗尽时，同一次语音会自动尝试在线的 Home Node SenseVoice。两者均不可用时只返回稳定的 `STTUnavailable`，文字聊天、历史和记忆不受影响。

生产版本为 `p9tts-20260902-0249-51d51f0`。Cloud 状态已报告 `tencent-sentence-recognition available=true` 和 `tts=available`，Home Node 在线并声明 `speech_to_text` 能力。此前准备的阿里云百炼 Qwen 适配仍作为非默认备用保留，不是生产启动依赖。

## 安全与费用控制

- 腾讯云语音识别服务已开通，后付费保持关闭；未点击“开通后付费”。
- CAM 子用户为 `miru-asr-prod`，仅允许编程访问，并只绑定自定义策略 `MiruASRSentenceRecognitionOnly`。
- 策略只允许 `asr:SentenceRecognition`，不包含付费模式、财务、控制台管理或自助管理密钥权限。
- 自动生成的旧凭据已停用并永久删除；新凭据未写入仓库、聊天记录或日志。
- 生产 Secret 位于 `/opt/miru/secrets/`，属主 `10001:10001`、权限 `0400`，以只读文件挂载进容器。
- Provider 只有在 SecretId、SecretKey 和 `billing_guard: postpay-disabled` 三者齐全时才会实例化。该 guard 是 Miru 的第二道操作门，不替代腾讯云计费设置。
- 日志只保留异常类型或腾讯错误码，不记录密钥、响应消息、音频或识别文本；运行时 Secret 与转写文本扫描未发现泄露。
- 手机 PCM16 音频只在内存中 Base64 编码。腾讯链路最大 60 秒；家庭节点回退固定为 16kHz、60 秒和 1,920,000 原始字节。
- Home Node 回退通过独立 Node Token 认证的 WSS 连接发送，不写临时音频文件，不开放任意命令执行。
- Cloud TTS 使用 `edge-tts 7.2.8` 的微软 Edge 在线中文音色，不需要 API Key、云账号或后付费设置。它不提供正式 SLA，失败或超时只降级为文字回复。
- TTS 设置 20 秒超时，拒绝空文本/空音频；第三方异常消息和合成文本不会写入日志。

## 腾讯云接口

- 接口：`SentenceRecognition`
- 域名：`https://asr.tencentcloudapi.com`
- 模型：`16k_zh-PY`（中英粤）
- 输入：16kHz、单声道、PCM16，Base64 放在 JSON 请求内
- 签名：TC3-HMAC-SHA256

官方限制和参数见[一句话识别 API](https://cloud.tencent.com/document/api/1093/35646)，免费额度与后付费开关见[语音识别计费说明](https://cloud.tencent.com/document/product/1093/35686)。

## 已完成验证

- 后端完整回归：136 passed，1 skipped（仅沙箱 DPAPI）。
- Docker Compose 生产配置静态校验通过。
- 生产 API 容器健康，数据库 `quick_check=ok`。
- 真实腾讯 `SentenceRecognition` 短音频调用成功，识别结果长度为 6 个字符；证据不保存识别文本。
- 同一短音频经 Home Node SenseVoice 识别成功，确认免费本地回退目标可用。
- Home Node 计划任务处于 Running，Cloud 可见 `speech_to_text=true`。
- Tailnet HTTPS `/healthz` 返回正常。
- 外部 `/api/debug/stt` 继续由生产 Caddy 返回 404，调试接口未暴露。
- 真实 Edge TTS 本地与生产容器烟测均成功；生产输出 19,584 字节 MP3，不保留音频或文本证据。
- Cloud 状态报告 `tts=available`，外部 `/api/debug/tts` 继续由生产 Caddy 返回 404。
- 激活后运行日志扫描未发现服务器 Token、腾讯凭据或 TTS 烟测文本。
- 部署临时凭据副本、远端测试音频和临时归档已删除；本地仅保留 ACL 保护的原始密钥 CSV。

## 激活处置记录

激活过程触发了保护性回滚，但未造成数据损坏或密钥泄露：

1. 首次候选启动前尚未安装 Secret，检查失败并自动回滚，未切换当前版本或修改数据库。
2. 初版部署脚本使用了错误的 Compose project directory，使配置路径被错误解析；旧版本一度不健康。随后用正确的 `/opt/miru/app/current/config` 恢复旧版本，并修正所有 Compose 调用。
3. 第二次候选已经健康，但验收脚本读取了过期的顶层 `stt_engine` 字段，因而自动回滚；校验已改为读取 `capabilities.stt`。
4. 修正后的第三次激活成功。当前版本、容器健康、数据库完整性、Cloud STT、Home Node 回退和真实 Provider 调用均已再次验证。

当前回滚版本为 `p9stt-20260901-1854-76dae93`。TTS 激活前数据库备份位于 `/opt/miru/backups/miru_server-pre-p9tts-20260902-0249-51d51f0.db`，SHA-256 为 `659d18cda09ab22a1b9e1dbcc06f2384aae43d0d2ecfb004126e27f8697a2c16`；更早的 STT 激活备份也继续保留。

## 后续顺序

1. 在 iPhone 上完成语音闭环真机验收：Home Node 离线时由腾讯 Cloud 识别，并播放 Edge TTS 回答。
2. 验证 TTS 播放中断与服务不可用时的文字降级。
3. 关闭 Phase 8/9 其余物理验收项，再进入 Phase 10 备份恢复与监控。
