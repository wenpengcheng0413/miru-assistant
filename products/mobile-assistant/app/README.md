# Miru iOS 客户端（Flutter）

语音入口：录音（16kHz PCM16）→ WebSocket 上行 → 后端完成 STT/LLM/TTS → 事件与句级音频下行播放。
架构与交互设计见 [07-Flutter-iOS客户端.md](../docs/07-Flutter-iOS客户端.md)。

## 装配步骤（在任何装有 Flutter 的机器上，最终构建 IPA 需要 macOS + Xcode）

```bash
# 1. 生成平台壳工程（只用来拿 ios/ android/ 目录）
flutter create --org com.miru --project-name miru_app miru_app_tmp

# 2. 用本目录内容替换壳工程
#    把本目录（app/）下的 pubspec.yaml 与 lib/ 复制进 miru_app_tmp/（覆盖同名文件）

# 3. 拉依赖
cd miru_app_tmp && flutter pub get

# 4. 开发环境可在 App 设置页填写地址；生产构建通过 dart-define 注入 Cloud 地址
# 5. flutter run   （模拟器/真机调试）
```

## iOS 权限（ios/Runner/Info.plist）

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Miru 需要麦克风来听你说话</string>
<key>NSCameraUsageDescription</key>
<string>Miru 需要相机来拍摄并分析图片</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Miru 需要访问照片以分析你选择的图片</string>
```

生产 Tailnet/Public Profile 不声明 Bonjour、本地网络权限或 ATS 明文例外。仅在开发壳工程确实需要局域网自动发现时添加这些开发权限。

## 自签部署（SideStore + LiveContainer，iOS 17）

1. `flutter build ipa --release --no-codesign`（需 macOS + Xcode）
2. 按 SideStore/LiveContainer 流程签名安装（LiveContainer JIT-less 模式需与宿主同证书签名）
3. 已知限制：无推送、无 App Extensions、7 天刷新一次；麦克风为普通权限，可用

## Cloud Profile

生产 IPA 以以下构建参数固定 Cloud Profile；App Token 不进入构建参数或源码，首次安装后在设置页写入 Keychain：

```bash
flutter build ipa --release --no-codesign \
  --dart-define=MIRU_DEPLOYMENT_PROFILE=tailnet \
  --dart-define=MIRU_BASE_URL=https://<设备名>.<tailnet>.ts.net
```

`tailnet` 与 `public` Profile 强制 HTTPS/WSS 并禁用 Bonjour；只有 `development` Profile 允许局域网发现和 HTTP 调试。
