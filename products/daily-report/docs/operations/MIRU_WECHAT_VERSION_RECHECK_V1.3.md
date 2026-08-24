# Miru 微信版本兼容重新调查报告 V1.3

**Date**: 2026-07-25
**Status**: 调查完成 / 待用户验证
**Trigger**: 4.0.3.22 被服务器拒绝登录（"需要更新版本"）

---

## 1. 关键发现：降级策略已死

### 用户测试结论

```
微信 4.0.3.22 → 客户端可启动 → 服务器拒绝登录 → "需要更新版本"
```

这确认了一个关键事实：

```
┌──────────────────────────────────────────────────────────────┐
│  登录截止线 (login cutoff) 在 4.0.3.22 之上                   │
│  密钥内存截止线 (key memory cutoff) 在 4.0.3.36                │
│                                                              │
│  → 不存在任何版本同时满足「能登录」且「内存扫描可获取 key」      │
│  → 降级到内存扫描版本 = 死路                                    │
└──────────────────────────────────────────────────────────────┘
```

**因此，V1.2 方案（降级到 4.0.3.22）已废弃。**

---

## 2. 技术路线重新评估

### 2.1 两种 Key 获取技术对比

| | 内存扫描 (Memory Scan) | DLL Hook (setCipherKey 拦截) |
|---|---|---|
| **原理** | 扫描进程内存搜索 `x'<96hex>'` 模式 | 注入 DLL，hook `setCipherKey` 函数 |
| **时机** | 微信运行时（key 需在内存中） | 微信登录瞬间（key 必经此函数） |
| **4.0.0 ~ 4.0.3.22** | ✅ 可用 | ✅ 可用 |
| **4.0.3.36 ~ 4.0.x** | ❌ Key 被清除 | ✅ 可用 |
| **4.1.x (含 4.1.11.53)** | ❌ Key 被清除 | ✅ 可用 |
| **代表工具** | wechat-dump-rs, wechat-decrypt, PyWxDump | chatlog_alpha, wx_key.dll, JinDaGe Skill |
| **管理员权限** | 需要 | 需要 |
| **防病毒误报** | 低 | 中（DLL 注入行为） |
| **版本依赖** | 强依赖（每个版本需更新偏移） | 弱依赖（基于字符串搜索定位函数） |

### 2.2 核心结论

> **DLL Hook 方案是唯一可行路径。内存扫描方案在可登录版本上已全部失效。**

---

## 3. 版本兼容矩阵（修订版）

| 微信版本 | 能否登录 | 内存扫描 | DLL Hook | 数据库格式 | Miru 兼容 | 推荐 |
|---|---|---|---|---|---|---|
| **4.0.0 ~ 4.0.3.22** | ❌ 被拒绝 | ✅ | ✅ | SQLCipher 4 | ✅ | ⛔ 无法登录 |
| **4.0.3.36 ~ 4.0.3.x** | ⚠️ 未知 | ❌ Key 清除 | ✅ | SQLCipher 4 | ✅ | ⛔ 登录不确定 |
| **4.0.5.x** | ⚠️ 未知 | ❌ | ✅ | SQLCipher 4 | ✅ | ⚠️ 未验证 |
| **4.0.8.x ~ 4.0.9.x** | ⚠️ 未知 | ❌ | ✅ | SQLCipher 4 | ✅ | ⚠️ 未验证 |
| **4.1.0.x** | ⚠️ 可能 | ❌ | ✅ | SQLCipher 4 | ✅ | ⚠️ 未验证 |
| **4.1.5.x** | ✅ 大概率 | ❌ | ✅ **已验证** | SQLCipher 4 | ✅ | ⭐ **推荐** |
| **4.1.10.x ~ 4.1.11.x** | ✅ 确认 | ❌ | ⚠️ **实验性** | SQLCipher 4 | ✅ | ⭐ **当前版本** |

### 关键说明

- **登录截止线位置**：在 4.0.3.22 和 4.1.5.x 之间，精确位置未知。保守估计 ≥ 4.1.0 可登录。
- **DLL Hook 已验证版本**：chatlog_alpha 官方测试通过 **4.1.5.30**（Windows）
- **DLL Hook 未验证版本**：4.1.10+ 标注为 "实验性"，但 macOS 4.1.11.54 已确认可用（Frida 方案）

---

## 4. 可用工具评估

### 4.1 主力推荐：chatlog_alpha

| 维度 | 评价 |
|------|------|
| **仓库** | `github.com/CJYKK/chatlog_backup` |
| **活跃度** | ⭐⭐⭐⭐⭐ 2026年1月仍在更新 |
| **内置 DLL** | wx_key1.dll + wx_key2.dll（双 DLL 备用） |
| **已验证版本 (Win)** | 4.1.5.30 |
| **实验性支持 (Win)** | 4.1.10+ |
| **已验证版本 (Mac)** | 4.1.11.54 ✅ |
| **工作流程** | 先启动 chatlog → 启动微信 → 点击登录 → 自动捕获 key |
| **额外功能** | HTTP API, MCP Server, 消息查询, 图片解密, 朋友圈支持 |
| **风险** | wx_key 原始仓库已 DMCA，但 DLL 通过 chatlog_alpha 继续分发 |

### 4.2 备选：wechat-decrypt (328336690)

| 维度 | 评价 |
|------|------|
| **仓库** | `github.com/328336690/wechat-decrypt` |
| **方式** | 内存扫描 (`find_all_keys.py`) |
| **4.1.x 兼容** | ❌ 使用 `x'<96hex>'` 模式扫描，4.0.3.36+ 已失效 |
| **结论** | **不适用于当前场景** |

### 4.3 备选：JinDaGe WeChat Export Skill

| 维度 | 评价 |
|------|------|
| **方式** | 捆绑 wx_key.dll v2.1.8，DLL Hook |
| **与 chatlog_alpha 关系** | 使用相同的 DLL，本质相同 |
| **结论** | chatlog_alpha 失败后的候选 |

### 4.4 手动方案：x64dbg + Frida Hook

如果所有自动化工具都失败，可以手动 hook：

```
原理：
  1. 用 x64dbg 附加 Weixin.exe
  2. 在 Weixin.dll 中搜索字符串 "com.Tencent.WCDB.Config.Cipher"
  3. 交叉引用定位 setCipherKey 函数
  4. 在函数入口设断点（RDX = cipherKey 指针）
  5. 登录微信，断点触发
  6. [RDX+0x8] → m_buffer（32 字节 key）
  7. [RDX+0x10] → m_size（应为 0x20）

或者用 Frida 脚本自动化这个过程。

参考：bbs.kanxue.com/thread-287761-1.htm
```

---

## 5. 最少尝试次数测试方案

### 测试矩阵

```
                    ┌──────────────────────────────────┐
                    │  Attempt 1: chatlog_alpha         │
                    │  目标版本: 当前 4.1.11.53         │
                    │  操作: 下载 → 运行 → 获取 key     │
                    │  风险: 极低（不卸载微信）           │
                    │  耗时: ~15 分钟                    │
                    └──────────────┬───────────────────┘
                                   │
                        ┌──────────┴──────────┐
                        │ 成功                 │ 失败
                        ▼                      ▼
                 ✅ 拿到 key        ┌──────────────────────────────┐
                 直接用 Miru         │  Attempt 2: 降级到 4.1.5.30    │
                                    │ 操作: 安装旧版 → 登录          │
                                    │ → chatlog_alpha → 获取 key    │
                                    │ 风险: 中（需卸载）              │
                                    │ 耗时: ~1 小时                  │
                                    └──────────────┬───────────────┘
                                                   │
                                        ┌──────────┴──────────┐
                                        │ 成功                 │ 失败
                                        ▼                      ▼
                                 ✅ 拿到 key        ┌──────────────────────────┐
                                 直接用 Miru         │  Attempt 3: 手动 Hook     │
                                                    │ 工具: x64dbg + Python     │
                                                    │ 操作: 定位 setCipherKey   │
                                                    │ → 断点捕获 key            │
                                                    │ 风险: 中（技术难度高）     │
                                                    │ 耗时: ~2-4 小时           │
                                                    └──────────────┬───────────┘
                                                                   │
                                                        ┌──────────┴──────────┐
                                                        │ 成功                 │ 失败
                                                        ▼                      ▼
                                                 ✅ 拿到 key        ┌──────────────────────┐
                                                 直接用 Miru         │  外部 Key Provider    │
                                                                    │  等待社区工具更新      │
                                                                    │  或手机端数据方案      │
                                                                    └──────────────────────┘
```

---

## 6. 各 Attempt 详细操作

### Attempt 1: chatlog_alpha 直接对 4.1.11.53（推荐首先执行）

```powershell
# 步骤 1: 下载 chatlog_alpha
# 访问 https://github.com/CJYKK/chatlog_backup/releases
# 下载最新 Windows 版本 (chatlog_alpha_windows_amd64.zip)

# 步骤 2: 解压并放置 DLL
# 解压到不含中文的路径，例如 C:\tools\chatlog_alpha\
# 确认 lib/windows_x64/ 下有 wx_key1.dll 和 wx_key2.dll

# 步骤 3: 完全退出微信
# 任务管理器 → 结束 Weixin.exe 进程

# 步骤 4: 以管理员身份运行 chatlog_alpha.exe

# 步骤 5: 在 TUI 界面选择「重启并获取密钥」
#   程序会启动微信
#   在微信登录界面点击「登录」
#   程序自动捕获 key

# 步骤 6: 记录输出的 key
#   格式: x'<64 hex chars>'

# 步骤 7 (可选): 如果 wx_key1.dll 无效，尝试 wx_key2.dll
```

**预期结果**：拿到数据库 key → 跳到 Section 7 Miru 集成。

**失败条件**：DLL 注入后无 key 输出 / 微信崩溃 / 程序报错。

### Attempt 2: 降级到 4.1.5.30 + chatlog_alpha

```powershell
# 前提: Attempt 1 失败

# 步骤 1: 备份当前微信数据
robocopy "E:\wechatfiles" "E:\wechatfiles_backup_4.1.11" /E /COPYALL /R:3 /W:5

# 步骤 2: 手机微信 → 聊天记录迁移 → 备份到电脑（安全网）

# 步骤 3: 卸载微信 4.1.11.53
# 控制面板 → 程序和功能 → 卸载微信
# 手动删除残留目录（同 V1.2 Section 4.3）

# 步骤 4: 下载微信 4.1.5.11 或 4.1.5.30
# 从 https://github.com/cscnk52/wechat-windows-versions/releases
# 或 https://github.com/iibob/wechat-win-archive/releases

# 步骤 5: 安装 + 登录 + 恢复聊天记录
# 关闭自动更新

# 步骤 6: 执行 Attempt 1 的步骤 3-7
```

**成功概率**：高于 Attempt 1（chatlog_alpha 明确测试过 4.1.5.x）

### Attempt 3: 手动 x64dbg Hook

```powershell
# 前提: Attempt 1 和 2 均失败

# 准备:
#   - x64dbg (https://x64dbg.com/)
#   - Python 3.11+ 带 pymem

# 步骤 1: 启动 x64dbg，附加到 Weixin.exe

# 步骤 2: 在 Symbols 中找到 Weixin.dll
#   右键 → Search for → Current Module → String references
#   搜索 "com.Tencent.WCDB.Config.Cipher"

# 步骤 3: 跟随交叉引用到 setCipherKey 调用点

# 步骤 4: 在调用点设置断点
#   函数签名: setCipherKey(this=RCX, cipherKey=RDX, ...)
#   [RDX + 0x8] = m_buffer (32 字节 key)
#   [RDX + 0x10] = m_size (0x20)

# 步骤 5: 点击微信登录
#   断点触发 → 查看 RDX → 读取 32 字节 → 这就是 key

# 步骤 6: hex 编码 → 得到 x'<64 hex>'
```

**备选**: 用 Frida 脚本自动化（需要 Node.js + frida-python）

---

## 7. 获取 Key 后的 Miru 集成

无论通过哪种方式拿到 key，Miru 集成步骤相同：

```yaml
# 编辑 config/settings.yaml
wechat:
  database_key: "x'<64 hex chars>'"   # 手动提供，跳过自动提取
```

```powershell
# 验证流程
miru doctor     # 检查环境
miru decrypt    # 验证解密（使用配置文件中的 key）
miru groups     # 列出群聊
miru read       # 读取消息
miru run --dry-run  # 端到端测试（控制台输出日报）
```

**Miru 代码不需要任何修改** — 只需在配置文件中提供 key。

---

## 8. 最终备用方案

### 如果三个 Attempt 全部失败

| 方案 | 可行性 | 说明 |
|------|--------|------|
| **等待 chatlog_alpha 更新** | 中 | 社区活跃，4.1.10+ 支持可能很快完善 |
| **虚拟机 + 4.1.5.30** | 高 | 完全隔离，但需要 VM 资源 + 聊天记录同步 |
| **macOS 方案** | 中 | macOS 4.1.11.54 已确认可用（Frida Hook），如果有 Mac |
| **手机端数据导出** | 低 | Android root/iOS 越狱后直接读取手机数据库，绕过 PC |
| **放弃实时读取，改用导出** | 中 | 定期手动用 chatlog_alpha 导出 JSON → Miru 读取 JSON 而非数据库 |
| **企业微信替代** | 低 | 对个人用户不可行 |

### 推荐的终极兜底：「定期导出」模式

如果 DLL Hook 方案不稳定，可以调整 Miru 的数据入口：

```
chatlog_alpha (手动/定时导出 JSON)
    │
    ▼
Miru JSON Collector (替换 wechat_reader.py)
    │
    ▼
filter → llm → report → notify
```

但这需要修改 Miru collector 层（小改动，不影响下游模块）。

---

## 9. 总结

| 结论 | 内容 |
|------|------|
| **V1.2 方案废弃原因** | 4.0.3.22 无法登录，所有 ≤ 4.0.3.36 版本均可能被拒绝 |
| **新核心技术路线** | DLL Hook（setCipherKey 拦截），非内存扫描 |
| **推荐工具** | chatlog_alpha（CJYKK/chatlog_backup） |
| **推荐测试顺序** | ① 当前 4.1.11.53 ② 降级 4.1.5.30 ③ 手动 x64dbg |
| **Miru 集成方式** | `wechat.database_key` 配置字段（外部 Key Provider） |
| **Miru 代码改动** | **零**（如果 config 已支持 manual key）/ **< 20 行**（如果需新增配置字段） |
| **预计最短路径** | Attempt 1 成功 → 15 分钟内拿到 key → Miru 端到端测试 |

---

## 附录 A：工具下载链接汇总

| 工具 | 地址 |
|------|------|
| chatlog_alpha | `https://github.com/CJYKK/chatlog_backup/releases` |
| 微信历史版本 (cscnk52) | `https://github.com/cscnk52/wechat-windows-versions/releases` |
| 微信历史版本 (iibob) | `https://github.com/iibob/wechat-win-archive/releases` |
| x64dbg | `https://x64dbg.com/` |
| Frida | `https://frida.re/` |
| 看雪论坛 setCipherKey 逆向 | `https://bbs.kanxue.com/thread-287761-1.htm` |
| 微信解密方法汇总 (vcvit) | `https://blog.vcvit.me/2026/02/16/how-to-decrypt-wechat-database/` |

## 附录 B：微信 4.x 版本架构速查

```
4.0.0 ─── 4.0.3.22 ─── 4.0.3.36 ─── 4.0.x ─── 4.1.0 ─── 4.1.5.x ─── 4.1.11.x
  │                     │            │                              │
  │                     │            │                              │
  ├─ 内存扫描 ✅        │            ├─ 内存扫描 ❌                  │
  ├─ DLL Hook ✅        │            ├─ DLL Hook ✅                  │
  ├─ 可登录 ❌          │            ├─ 可登录 ⚠️                   │
  │                     │            │                              │
  │          ┌──────────┘            │                              │
  │          │ 登录截止线 (在此之后)    │                              │
  │          │                        │                              │
  │          └── 4.0.3.22 测试确认 ───┘                              │
  │              "需要更新版本"                                       │
  │                                                                  │
  └── Key 内存截止线 ─────────────────┘                              │
      4.0.3.36 起 Key 主动清除                                       │
```

---

*End of Re-evaluation Report V1.3*
