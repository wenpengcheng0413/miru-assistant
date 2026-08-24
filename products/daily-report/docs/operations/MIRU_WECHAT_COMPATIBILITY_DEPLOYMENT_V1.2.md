# Miru Assistant — 微信兼容部署方案 V1.2

**Date**: 2026-07-25
**Status**: 工程调查完成 / 待用户执行
**Target**: 让 Miru V1.1 首次成功读取真实微信聊天数据

---

## 1. 当前状态总结

### 环境信息

| 项目 | 值 |
|------|-----|
| OS | Windows 10 Pro (build 19045) |
| 微信版本 | **4.1.11.53** (Weixin.exe) |
| 数据目录 | `E:\wechatfiles\xwechat_files\<wxid>\` |
| 目录结构 | 新版 (`db_storage/contact/`, `db_storage/message/`) |
| Miru 代码 | V1.1 完成，237 测试通过 |
| 阻塞点 | **无法获取数据库解密密钥** |

### 已尝试方案（均失败）

| # | 方案 | 工具 | 结果 |
|---|------|------|------|
| 1 | 内存模式扫描 | wechat-decrypt (Miru 内置适配器) | `x'<96hex>'` pattern 未找到 |
| 2 | PyWxDump API | pywxdump v3.1.46 | "Version Is Not Supported", key=None |
| 3 | PyWxDump + monkey-patch | 绕过进程名检查 | 同样版本不支持 |
| 4 | 自定义 pymem 扫描 | scan_keys_debug.py | 0 key candidates |

### 根因

**微信从 4.0.3.36 起，登录完成后主动清除内存中的数据库密钥。** 所有基于运行时内存扫描的工具（PyWxDump, wechat-decrypt, wechat-dump-rs）均依赖密钥持续存在于进程内存中。这不是 Miru 代码的问题 — Miru 的 SQLCipher 4 解密模块本身功能正常。

---

## 2. 微信版本兼容分析

### 2.1 三代微信数据库技术栈

| | 微信 3.x | 微信 4.0.x | 微信 4.1.x |
|---|---|---|---|
| **加密引擎** | SQLCipher 3 | SQLCipher 4 | SQLCipher 4 |
| **算法** | AES-256-CBC | AES-256-CBC | AES-256-CBC |
| **认证** | HMAC-SHA1 | HMAC-SHA512 | HMAC-SHA512 |
| **KDF 迭代** | 64,000 | 256,000 | 256,000 |
| **页大小** | 4096 | 4096 | 4096 |
| **核心 DLL** | WeChatWin.dll | Weixin.dll | Weixin.dll |
| **数据目录** | `WeChat Files/` | `xwechat_files/` | `xwechat_files/` |
| **进程名** | WeChat.exe | Weixin.exe | Weixin.exe |
| **Miru SQLCipher 模块** | ❌ 不兼容 | ✅ 兼容 | ✅ 兼容（算法层面） |

### 2.2 版本兼容矩阵

| 微信版本 | Key 获取 | 数据库格式 | Miru 兼容 | 推荐 | 备注 |
|---|---|---|---|---|---|
| **3.9.6 ~ 3.9.12** | ✅ wechat-dump-rs `--vv 3` | SQLCipher 3 | ❌ | ⛔ 不推荐 | Miru 针对 SQLCipher 4 设计，3.x 需改写解密模块 |
| **4.0.0.26** | ✅ 内存扫描 | SQLCipher 4 | ✅ | ⚠️ 可用 | 早期版本，可能有稳定性问题 |
| **4.0.1.x** | ✅ 内存扫描 | SQLCipher 4 | ✅ | ⚠️ 可用 | 测试版阶段 |
| **4.0.2.x** | ✅ 内存扫描 | SQLCipher 4 | ✅ | ✅ 推荐 | 稳定 |
| **4.0.3.22** | ✅ 内存扫描 | SQLCipher 4 | ✅ | ⭐ 最佳选择 | **最后一个被社区广泛验证的版本** |
| **4.0.3.36** | ⚠️ 边界版本 | SQLCipher 4 | ✅ | ⚠️ 谨慎 | Key 可能仍在内存，但社区反馈不一致 |
| **4.0.3.36+ ~ 4.0.x** | ❌ Key 清除 | SQLCipher 4 | ✅ | ⛔ 不可用 | Key 获取失败 |
| **4.1.x (含 4.1.11.53)** | ❌ Key 清除 | SQLCipher 4 | ✅ | ⛔ 当前版本 | **当前阻塞** |
| **4.1.10+** | ❌ 内存扫描死透 | SQLCipher 4 | ✅ | ⛔ 不可用 | 500 万+ 内存候选全部无效 |

### 2.3 关键结论

```
微信 4.0.3.22 = 最后可用的完整兼容版本
         ↑
    这是 Miru 的目标部署版本
```

**密钥跨次版本稳定性**：在 4.x 大版本内，SQLCipher 密钥格式和加密参数不变。同一个微信账号在同一台机器上重新登录后，密钥会重新生成。但如果先降级到 4.0.3.22 登录并提取 key，然后升级回 4.1.x，key 可能仍然有效（因为数据库文件本身不变，key 被保存在微信服务端/本地配置中）。

---

## 3. 推荐具体版本

### 首选：**微信 Windows 4.0.3.22**

| 维度 | 说明 |
|------|------|
| **Key 获取** | ✅ 内存扫描完全支持（`x'<96hex>'` pattern 稳定存在） |
| **数据库格式** | ✅ SQLCipher 4，Miru 原生支持 |
| **数据目录** | ✅ `xwechat_files/` 新版目录结构 |
| **稳定版** | ✅ 4.0.3.19 起转为正式版，4.0.3.22 是成熟版本 |
| **社区验证** | ✅ wechat-dump-rs, wechat-decrypt, chatlog 均验证通过 |
| **Windows 10 兼容** | ✅ 完全兼容 |

### 备选：**微信 Windows 4.0.2.17 或 4.0.3.36**

仅在 4.0.3.22 不可用时考虑。

### 下载来源

| 仓库 | 地址 | 备注 |
|------|------|------|
| cscnk52/wechat-windows-versions | `https://github.com/cscnk52/wechat-windows-versions/releases/tag/v4.0.3.22` | **首选**，明确有 4.0.3.22 |
| iibob/wechat-win-archive | `https://github.com/iibob/wechat-win-archive/releases` | 持续更新，收录 4.0+ 版本 |
| Rodert/wechat-windows-versions | `https://github.com/Rodert/wechat-windows-versions/releases` | 官方原版安装包 |
| tom-snow/wechat-windows-versions | `https://github.com/tom-snow/wechat-windows-versions/releases` | 备选 |

**注意**：下载后校验 SHA256（如果仓库提供），确保安装包未被篡改。

---

## 4. 安装步骤

### 4.1 备份当前微信数据（关键！）

```powershell
# 1. 完整复制数据目录（保险措施）
robocopy "E:\wechatfiles" "E:\wechatfiles_backup_20260725" /E /COPYALL /R:3 /W:5

# 2. 单独备份数据库文件（最小备份）
robocopy "E:\wechatfiles\xwechat_files\<wxid>\db_storage" `
         "E:\wechat_db_backup_20260725" /E /R:3 /W:5

# 3. 记录备份校验
dir /s "E:\wechatfiles_backup_20260725" > backup_inventory.txt
```

### 4.2 手机端聊天记录备份（推荐）

```
手机微信操作：
  我 → 设置 → 通用 → 聊天记录迁移与备份
  → 备份与恢复
  → 备份到电脑

确认：
  - 备份完成后，在手机上能看到「备份已完成」提示
  - 记录备份时间
```

**这个流程是可行的。** 微信官方的聊天记录迁移功能在 3.x/4.x 之间是兼容的 — 它传输的是消息内容层面的数据，不是数据库文件。恢复时由目标微信版本重新写入本地数据库。

### 4.3 清理步骤

#### 需要卸载/删除的目录

```
卸载:
  控制面板 → 程序和功能 → 卸载「微信」

手动删除残留目录（如果存在）:
  C:\Users\<用户名>\AppData\Local\Tencent\WeChat\
  C:\Users\<用户名>\AppData\Roaming\Tencent\WeChat\
  C:\Users\<用户名>\Documents\xwechat_files\     ← 新版数据目录
  %TEMP%\Tencent\
  %TEMP%\WeChat\
  E:\wechatfiles\                                 ← 用户自定义数据目录
```

**重要**：在删除 `E:\wechatfiles\` 之前，务必确认步骤 4.1 的备份已完成！

#### 不需要删除的内容

```
不需要删除:
  - 备份目录 (E:\wechatfiles_backup_20260725\)
  - 手机端聊天记录（不受影响）
  - Miru 项目目录
```

### 4.4 安装微信 4.0.3.22

```powershell
# 1. 以管理员身份运行安装包
WeChatSetup_4.0.3.22.exe

# 2. 安装时选择自定义数据目录
#    安装位置: C:\Program Files\Tencent\WeChat\
#    数据目录: E:\wechatfiles\   (与原路径一致)

# 3. 安装完成后立即禁止自动更新
#    微信设置 → 通用 → 取消勾选「有更新时自动升级微信」
```

### 4.5 恢复聊天记录

```
手机微信操作：
  我 → 设置 → 通用 → 聊天记录迁移与备份
  → 备份与恢复
  → 恢复到电脑

确认：
  - PC 微信和手机微信在同一 WiFi 下
  - 恢复过程可能需要较长时间（取决于聊天记录大小）
```

---

## 5. 密钥提取工具对比

| 工具 | 方式 | 平台 | 4.0.3.22 兼容 | 优点 | 缺点 |
|------|------|------|--------------|------|------|
| **wechat-dump-rs** | 内存搜索 | Windows | ✅ 已验证 | 一键操作，自动解密 | 需下载 exe |
| **wechat-decrypt (328336690)** | pymem 扫描 | Windows | ✅ 已验证 | Python 原生，有 MCP Server | 需管理员权限 |
| **weixin-decrypte-script** | pymem 扫描 | Windows | ✅ | 轻量 | 功能较少 |
| ~~PyWxDump~~ | 内存偏移 | Windows | ❌ 仅限旧版 | — | 不支持 4.x |
| ~~wx_key~~ | DLL 注入 | Windows | ❌ 已删库 | — | DMCA 下架 |

### 推荐使用 wechat-dump-rs（最简单）

```powershell
# 下载
# https://github.com/0xlane/wechat-dump-rs/releases

# 直接运行（自动检测微信进程并输出 key）
.\wechat-dump-rs.exe

# 或者一键导出所有 key + 自动解密数据库
.\wechat-dump-rs.exe -a
```

---

## 6. 测试 Checklist

### Phase A: 环境验证

```
[ ] A1. 确认微信版本
      微信设置 → 关于微信 → 应显示 4.0.3.22

[ ] A2. 确认自动更新已关闭
      微信设置 → 通用 → 「有更新时自动升级微信」取消勾选

[ ] A3. 确认聊天记录已恢复
      随机打开几个群聊，确认最近消息可见

[ ] A4. 运行 miru doctor
      cd "E:\vibe coding\miru-assistant"
      venv\Scripts\activate
      miru doctor
      
      检查输出:
      - WeChat process: Weixin.exe detected ✓
      - Version: 4.0.3.22 ✓
      - Data directory: E:\wechatfiles\xwechat_files\... ✓
      - Admin: Yes ✓
      - Dependencies: All installed ✓
```

### Phase B: 密钥提取

```
[ ] B1. 关闭微信（重要：先退出微信再重新打开，确保持久化 session 数据已写入）

[ ] B2. 重新打开微信，登录确认

[ ] B3. 运行 wechat-dump-rs
      .\wechat-dump-rs.exe
      
      检查输出:
      - 应输出至少 1 个 key（主数据库 key）
      - Key 格式: x'<64 hex chars>'

[ ] B4. 保存 key
      将输出的 key 复制保存到安全位置

[ ] B5. (可选) 使用 wechat-dump-rs 自动解密验证
      .\wechat-dump-rs.exe -a
      检查解密后的 .db 文件能否用 DB Browser for SQLite 打开
```

### Phase C: Miru 解密验证

```
[ ] C1. 配置 key
      编辑 config/settings.yaml，添加:
      wechat:
        database_key: "x'<你提取的64位hex>'"

[ ] C2. 运行 miru decrypt
      miru decrypt
      
      检查输出:
      - 应显示成功解密 contact.db
      - 应显示成功解密 message_0.db
      - 应显示 schema 检查通过

[ ] C3. 运行 miru groups
      miru groups
      
      检查输出:
      - 应列出所有群聊名称
      - 确认目标群在列表中
```

### Phase D: 消息读取验证

```
[ ] D1. 运行 miru read
      miru read
      
      检查输出:
      - 应显示群消息数量
      - 应显示消息时间范围
      - 应包含实际消息内容预览
```

### Phase E: 端到端测试

```
[ ] E1. 运行 miru run --dry-run
      miru run --dry-run
      
      检查输出:
      - Stage 1: Environment check ✓
      - Stage 2: Key extraction / decrypt ✓
      - Stage 3: Message filtering ✓
      - Stage 4: LLM analysis (DeepSeek) ✓
      - Stage 5: Report generation ✓
      - Stage 6: Notification (console mode) ✓
      - 终端输出完整的 Markdown 日报

[ ] E2. 检查日志
      查看 logs/ 目录下的日志文件
      确认无 ERROR 级别日志

[ ] E3. (可选) 发送真实推送
      配置 PushPlus token，运行:
      miru run
      手机应收到来自「Miru Daily Assistant」的推送消息
```

### Phase F: 定时任务验证

```
[ ] F1. 运行 setup_scheduler.ps1
      powershell -ExecutionPolicy Bypass -File scripts/setup_scheduler.ps1

[ ] F2. 检查任务计划程序
      taskschd.msc → 任务计划程序库 → 找到 Miru Daily Report

[ ] F3. 手动触发一次
      右键 → 运行
      等待完成后检查日志和推送
```

---

## 7. 风险与备用方案

### 7.1 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 4.0.3.22 安装包已从 GitHub 下架 | 低 | 高 | 多个备选仓库 |
| 聊天记录恢复失败/不完整 | 中 | 中 | 步骤 4.1 的完整备份 + 手机端聊天记录不受影响 |
| 4.0.3.22 在 Windows 10 上有兼容问题 | 低 | 中 | 备选 4.0.2.17 |
| key 提取工具也被 DMCA 全部下架 | 低 | 高 | wechat-decrypt 的 pymem 方法是纯 Python，无法被下架 |
| 微信强制升级 | 中 | 中 | hosts 屏蔽 + 防火墙规则 |
| LLM API 调用失败 | 低 | 低 | Pipeline 有完整错误处理和重试机制 |

### 7.2 阻止微信自动升级

```powershell
# 方法 1: hosts 文件屏蔽（推荐）
# 以管理员身份编辑 C:\Windows\System32\drivers\etc\hosts
# 添加:
127.0.0.1 dldir1.qq.com
127.0.0.1 dldir1v6.qq.com
127.0.0.1 update.weixin.qq.com

# 方法 2: 防火墙出站规则
# 新建出站规则 → 程序 → Weixin.exe → 阻止连接
```

### 7.3 备用方案（按优先级）

#### 方案 A: 双微信环境（如果不想卸载当前微信）

```
思路:
  1. 在另一个 Windows 用户账户下安装 4.0.3.22
  2. 登录微信并迁移聊天记录
  3. 在该账户下运行 Miru
  4. 当前账户的 4.1.11.53 保持不变

优点: 不影响当前使用
缺点: 需要两个 Windows 账户，切换不便
```

#### 方案 B: 虚拟机测试

```
思路:
  1. 在 Hyper-V / VirtualBox 中创建 Windows 10 VM
  2. 安装微信 4.0.3.22
  3. 登录并迁移聊天记录
  4. 在 VM 中运行 Miru

优点: 完全隔离，不影响宿主机
缺点: VM 资源开销，消息同步延迟
```

#### 方案 C: 外部 Key Provider（不降级的情况下）

```
思路:
  1. 保持当前 4.1.11.53
  2. 使用 DLL Hook 方法获取 key（如 Frida/gzygood/DbkeyHook）
  3. 将 key 写入 config/settings.yaml
  4. Miru 直接使用手动提供的 key

优点: 不需要降级
缺点: Hook 方案复杂，相关工具多被 DMCA；不是 Miru 的核心能力范围

实现:
  Miru V1.1 只需添加一个 wechat.database_key 配置字段（工作量 < 20 行代码）
  Key 来源由用户通过外部手段提供
```

#### 方案 D: 等待社区更新

```
风险: 不确定等待时间
当前状态: 自 4.0.3.36 起（2024 年中），社区已有 1 年+ 未能突破内存扫描限制
结论: 不建议等待
```

#### 方案 E: 保留当前数据库备份 + 随时回滚

```
如果降级后出问题:
  1. 卸载 4.0.3.22
  2. 重新安装 4.1.11.53
  3. 恢复 E:\wechatfiles 备份
  4. 回到当前状态

关键: 步骤 4.1 的备份是安全网
```

---

## 8. 外部 Key Provider 实现说明（如需）

如果选择一个不降级的路径，Miru 只需最小的代码改动：

```yaml
# config/settings.yaml
wechat:
  database_key: ""  # 手动提供 32 字节 hex key (不带 x'' 包裹)
                     # 如果设置，跳过自动 key 提取
                     # 格式: x'<64 hex chars>' 或直接 64 hex chars
```

Miru Pipeline 中 `_collect_messages()` 的逻辑：
```
if config.wechat.database_key:
    key = parse_manual_key(config.wechat.database_key)
else:
    key = auto_extract_key(pid)
```

这已经在 Handoff V1.1 的 Section 10 Priority 1 中建议过。

---

## 9. 执行决策矩阵

```
                 ┌─────────────────────────────────┐
                 │  是否愿意卸载当前微信 4.1.11.53？   │
                 └──────────────┬──────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │ 是                    │ 否
                    ▼                       ▼
        ┌───────────────────┐   ┌──────────────────────┐
        │ 安装 4.0.3.22      │   │ 是否愿意使用虚拟机？     │
        │ → wechat-dump-rs   │   └──────────┬───────────┘
        │ → 提取 key         │       ┌──────┴──────┐
        │ → Miru 端到端测试   │       │ 是          │ 否
        └───────────────────┘       ▼              ▼
                            ┌──────────┐  ┌──────────────────┐
                            │ VM 方案   │  │ 外部 Key Provider │
                            │ (7.3-B)   │  │ (7.3-C)          │
                            └──────────┘  │ + 研究 Hook 方案   │
                                          └──────────────────┘
```

---

## 10. 总结

| 结论 | 内容 |
|------|------|
| **推荐版本** | 微信 Windows 4.0.3.22 |
| **Key 获取工具** | wechat-dump-rs (最简单) 或 wechat-decrypt (Python 原生) |
| **数据库格式** | SQLCipher 4，Miru 完全兼容 |
| **降级路径** | 手机备份 → 卸载 4.1.x → 安装 4.0.3.22 → 手机恢复 |
| **安全网** | `E:\wechatfiles` 完整备份（可随时回滚） |
| **预计工作量** | 2-4 小时（含备份/安装/恢复/测试） |
| **Miru 代码** | **不需要修改任何代码** |

**下一步**：用户按 Section 6 的 Checklist 逐步执行。

---

*End of Compatibility Deployment Plan V1.2*
