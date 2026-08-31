# Phase 9 Cloud STT 实施记录

日期：2026-09-01
状态：代码与生产清单已就绪；Provider 凭据、部署和真机验收待完成。

## 结论

App 显示 `STT 未启用` 不是微信语音消息转写故障。生产 Cloud profile 原先会把所有 STT 强制改成 `none`，且生产配置也明确使用 `engine: none`。因此 Home Node 已能转写微信 SILK 语音，并不代表手机麦克风的 Cloud STT 已启用。

本阶段新增阿里云百炼 Qwen ASR Cloud Provider：

- Cloud profile 继续禁止加载 SenseVoice、Whisper 和本地模型，但允许显式的 `qwen` 外部 Provider。
- Flutter 现有 PCM16 16kHz 协议不变；服务端只在内存中封装单声道 WAV，再以 Base64 Data URL 发给 Provider，不写临时音频文件。
- `qwen3-asr-flash` 是整句 HTTP 识别。Provider 声明 `supports_partial = false`，服务端不会每 800ms 重复上传累积音频，避免重复计费。
- Provider 异常只记录异常类型，不记录响应正文、密钥或音频；客户端收到稳定的 `STTUnavailable` 错误。
- `/api/status` 的 `stt` 能力现在返回结构化 `available/location/provider/reason`，旧 App 仍兼容。
- Qwen 调用不再误记为“本地 0 元 STT”；精确的外部 STT 费用入账留给 Cost Monitor 阶段。

## 生产启用门

生产清单已切换到 `stt.engine: qwen`，并从只读文件 `/opt/miru/secrets/stt_api_key` 注入 `MIRU_STT_API_KEY`。在该文件存在且非空之前，**不要激活新生产清单**，因为 Compose 会按 fail-closed 规则拒绝启动。

启用时需要：

1. 在阿里云百炼开通 Qwen ASR，并创建服务端 API Key。
2. 优先把 `base_url` 换成当前业务空间的北京专属 `compatible-mode/v1` 地址；当前共享地址保留为兼容默认值。
3. 将 Key 写入服务器 `/opt/miru/secrets/stt_api_key`，权限限制为部署用户可读。
4. 构建并原子激活新镜像，先验证 `/healthz`、`/readyz` 和带鉴权 `/api/status`。
5. 用短 WAV 调 `/api/debug/stt` 做 Provider 验证，再进行 iPhone 按住说话、松手终判、失败重试和 PC 关机测试。

## 验证结果

- 新增 Cloud STT 测试：Provider 配置门、Cloud profile、内存 WAV、响应解析、错误脱敏、生产 secret 清单。
- 服务端完整测试：`125 passed, 1 skipped`。跳过项为当前沙箱无法执行的真实 DPAPI 测试。
- Flutter analyze：无问题。
- Flutter test：`7 passed`。
- 新增文件的 Ruff 检查：通过。仓库全量 Ruff 仍有既存告警，不属于本阶段回归。

## 后续顺序

1. 完成 Qwen ASR 凭据与 Cloud STT 真机验收。
2. 接通现有 MiniMax TTS Provider 的生产凭据，完成 PC 关机语音问答闭环。
3. 关闭 Phase 8/9 尚未留证的物理验收项。
4. 进入 Phase 10：备份恢复演练、附件增量备份、容量/磁盘/Swap/Node 告警和恢复 Runbook。

## Provider 依据

- [阿里云百炼：Qwen-ASR API 参考](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference)
- [阿里云百炼：语音识别模型选型](https://help.aliyun.com/zh/model-studio/asr-model)
