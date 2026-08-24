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

# 4. 改默认服务器地址（lib/core/config.dart 顶部常量，或在 App 设置页改）
# 5. flutter run   （模拟器/真机调试）
```

## iOS 必改配置（ios/Runner/Info.plist）

```xml
<key>NSMicrophoneUsageDescription</key>
<string>Miru 需要麦克风来听你说话</string>
<key>NSCameraUsageDescription</key>
<string>Miru 需要相机来拍摄并分析图片</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Miru 需要访问照片以分析你选择的图片</string>
<key>NSLocalNetworkUsageDescription</key>
<string>Miru 需要连接你电脑上的后端服务</string>
<key>NSBonjourServices</key>
<array><string>_miru._tcp</string></array>
<!-- 局域网 HTTP 调试用 ATS 例外；上 Tailscale/frp 走 HTTPS 后可移除 -->
<key>NSAppTransportSecurity</key>
<dict>
  <key>NSAllowsLocalNetworking</key><true/>
  <key>NSAllowsArbitraryLoads</key><true/>
</dict>
```

## 自签部署（SideStore + LiveContainer，iOS 17）

1. `flutter build ipa --release --no-codesign`（需 macOS + Xcode）
2. 按 SideStore/LiveContainer 流程签名安装（LiveContainer JIT-less 模式需与宿主同证书签名）
3. 已知限制：无推送、无 App Extensions、7 天刷新一次；麦克风为普通权限，可用

## 与后端连通的三种地址

| 场景 | 设置页填写 |
|------|-----------|
| 同一 Wi-Fi 调试 | App 会自动发现 Miru；也可手填 `http://192.168.x.x:8765` |
| 推荐：Tailscale | `https://<电脑名>.xxx.ts.net:8765`（真证书，无需 ATS 例外） |
| 远期：frp+VPS | `https://miru.yourdomain.com` |
