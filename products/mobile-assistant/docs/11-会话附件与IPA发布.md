# 11 · 会话、附件、Vision 与 IPA 发布

## 本版功能

- 所有会话以 `server/data/miru_server.db` 为真实来源；手机左侧抽屉可新建、搜索、打开、重命名、删除会话。
- 后端每天建立一个一致性 SQLite 快照到 `server/data/backups/`，默认保留 30 天。
- 手机可拍照、选相册图片或选择 JPG/PNG/GIF/WebP、PDF、DOCX、XLSX/XLS、CSV、PPTX、TXT、Markdown。
- 图片和文档预览使用 `deepseek-v4-flash-vision-exp`；日常文字、语音仍使用 `deepseek-v4-flash`。
- 微信工具 `wechat_transcribe_voice` 在本机解码 SILK、使用本机 STT 转写并缓存，不上传原始语音。

## 服务器首次更新

```powershell
cd products/mobile-assistant/server
..\..\..\venv\Scripts\python.exe -m pip install -r requirements.txt
.\start_server.ps1
```

真实配置 `config/settings.yaml` 至少应包含：

```yaml
llm:
  model: deepseek-v4-flash
  vision_model: deepseek-v4-flash-vision-exp

tools:
  enabled:
    - wechat_transcribe_voice
```

API Key 仅保存在电脑环境变量 `MIRU_DEEPSEEK_API_KEY` 或被 Git 忽略的 `settings.yaml`，不要写进 App 或提交到仓库。

## 数据不会因 IPA 更新消失

聊天记录、附件、语音转写缓存都在电脑端 `server/data/`。覆盖安装或删除后重装 IPA，只要重新填写同一服务器地址和 token，就会从后端恢复会话列表。

不要手动删除以下目录：

```text
server/data/miru_server.db
server/data/attachments/
server/data/backups/
```

## 在 Codemagic 手动构建 IPA

仓库根目录已有 `codemagic.yaml`，工作流名称为 **Miru iOS Sideload IPA Build**。

1. 登录 Codemagic，选择 **Add application**，连接本 GitHub 仓库。
2. 确认它读取仓库根目录的 `codemagic.yaml`。
3. 在应用页选择 **Start new build**，工作流选 `miru-ios-build`，分支选包含本次改动的分支（通常为 `master`）。
4. 构建完成后，在 **Artifacts** 下载 `Miru.ipa`。
5. 用你原来使用的 SideStore/LiveContainer 签名安装。务必保持 Bundle ID `com.miru.miru_app` 和同一签名身份，才能作为同一 App 覆盖更新。

该工作流在云端自动生成 iOS 壳工程、注入麦克风/相机/相册/局域网权限，并产出未签名 IPA；因此不需要把 Apple 证书上传到 Codemagic。

## 首次验收清单

1. 打开手机 App 左上角菜单，确认能看到旧会话并可切换。
2. 新建会话后发送一张截图，确认回答中准确读取图片文字或图表。
3. 上传 CSV/XLSX/PDF，要求“列出关键结论并标明工作表/页码”。
4. 让 Miru 转写指定联系人最近的语音消息，确认结果含时间、说话人和文本。
5. 重装 IPA 后重新连接服务器，确认侧边栏历史仍存在。
