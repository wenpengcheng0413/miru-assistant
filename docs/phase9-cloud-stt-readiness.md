# Phase 9 免费优先 STT 实施记录

日期：2026-09-01
状态：腾讯云与家庭节点代码、配置门和离线测试已就绪；云账号凭据、部署和真机验收待完成。

## 当前结论

生产环境暂时保持 `stt.engine: none`，因此在没有完成腾讯云控制台安全设置前，不会发送音频、消耗额度或产生费用。此前准备的阿里云百炼 Qwen 适配仍保留为可选备用，但已移出生产默认值和启动必需密钥。

免费优先链路为：

1. 腾讯云“一句话识别”作为 Cloud 主 Provider，可在电脑关闭时工作。
2. 主 Provider 未配置、请求失败或免费额度耗尽时，同一次语音自动尝试在线的 Home Node SenseVoice。
3. 两者均不可用时只返回稳定的 `STTUnavailable`；文字聊天、历史和记忆不受影响。

## 安全与费用控制

- 腾讯 Provider 只有在 SecretId、SecretKey 和 `billing_guard: postpay-disabled` 三者齐全时才会实例化。
- `billing_guard` 不是腾讯云计费开关，而是 Miru 的第二道操作门。必须先在腾讯云控制台确认关闭后付费，再设置该值。
- 当前生产 Compose 不挂载任何 STT 密钥，也不要求 STT 密钥才能启动。
- Provider 请求使用 TC3-HMAC-SHA256；日志只保留异常类型或腾讯错误码，不记录密钥、响应消息、音频或识别文本。
- 手机 PCM16 音频只在内存中 Base64 编码。腾讯链路最大 60 秒；家庭节点回退也固定为 16kHz、60 秒和 1,920,000 原始字节。
- Home Node 回退通过现有独立 Node Token 认证的 WSS 连接发送，不写临时音频文件，不开放任意命令执行。

## 腾讯云接口选择

- 接口：`SentenceRecognition`
- 域名：`https://asr.tencentcloudapi.com`
- 模型：`16k_zh-PY`（中英粤）
- 输入：16kHz、单声道、PCM16，Base64 放在 JSON 请求内
- 签名：TC3-HMAC-SHA256

官方限制和参数见[一句话识别 API](https://cloud.tencent.com/document/api/1093/35646)，免费额度与后付费开关见[语音识别计费说明](https://cloud.tencent.com/document/product/1093/35686)。

## 启用门

后续需要用户授权的控制台步骤：

1. 登录腾讯云并确认语音识别服务的后付费处于关闭状态。
2. 使用 CAM 子用户或角色创建仅用于 ASR 的最小权限凭据，禁止使用主账号永久密钥。
3. 将 SecretId、SecretKey 作为服务器只读 Secret 写入，不写入仓库、App 或日志。
4. 只有完成第 1 步后，才设置 `MIRU_TENCENT_ASR_BILLING_GUARD=postpay-disabled`。
5. 部署后先用短测试 WAV 验证，再进行 iPhone、Home Node 离线和额度/Provider 失败回退验收。

## 已完成的离线验证范围

- 腾讯配置门、Cloud profile、PCM 请求、TC3 Authorization 头和响应解析。
- Provider 错误消息与密钥脱敏。
- Qwen 不再是生产默认值，生产启动不再依赖百炼密钥。
- Cloud Provider 不可用时自动回退 Home Node SenseVoice。
- Home Node 能力白名单、音频尺寸边界和动态 `/api/status`。

## 后续顺序

1. 完成腾讯云控制台的零账单保护与最小权限凭据。
2. 部署 Cloud 与 Home Node 更新，验证主链路和自动回退。
3. 完成 iPhone 麦克风 STT 真机验收。
4. 评估免费 TTS 路线，完成电脑关闭时的语音问答闭环。
5. 关闭 Phase 8/9 其余物理验收项，再进入 Phase 10 备份恢复与监控。
