# Miru Assistant — 中文文档

> AI 微信秘书 · 日报自动推送

## 项目简介

Miru Assistant 是一个运行在 Windows PC 上的 AI 微信助理。

它不是聊天机器人。它每天定时读取你指定的微信群消息，用 AI 识别重要信息，生成日报推送到你的手机微信。

## 核心功能

- **消息采集** — 自动读取微信 PC 端本地数据库（无需手动导出）
- **智能过滤** — 自动忽略闲聊、表情包、无意义消息
- **AI 总结** — DeepSeek 大模型识别通知、作业、Deadline、文件
- **日报推送** — PushPlus 推送 Markdown 日报到手机微信
- **定时运行** — Windows 任务计划，每天 21:00 自动执行

## 系统架构

```
  微信群消息 (微信 PC 本地加密数据库)
         │
         ▼
  ① 消息采集层 (SQLCipher 解密 + SQLite 查询)
         │
         ▼
  ② 消息过滤层 (去重 → 清洗 → 预分类 → 分组)
         │
         ▼
  ③ LLM 分析层 (DeepSeek V4 Flash API)
         │
         ▼
  ④ 日报生成层 (Jinja2 Markdown 模板)
         │
         ▼
  ⑤ 消息推送层 (PushPlus → 手机微信)
```

## 快速开始

### 环境要求

- Windows 10/11 x64
- Python 3.11+
- 微信 PC 版（已登录）
- DeepSeek API Key
- PushPlus Token

### 安装

```bash
# 克隆项目
git clone <your-repo-url> miru-assistant
cd miru-assistant

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate    # CMD
# 或: source venv/Scripts/activate  # Git Bash

# 安装
pip install -e .

# 初始化配置
cp config/settings.example.yaml config/settings.yaml
```

### 配置

编辑 `config/settings.yaml`：

```yaml
miru:
  groups:
    - "你的班级群名"
    - "AI交流群"

  llm:
    api_key: "${MIRU_DEEPSEEK_API_KEY}"  # 环境变量

  notifiers:
    - type: "pushplus"
      token: "${MIRU_PUSHPLUS_TOKEN}"
```

设置环境变量：

```bash
# Windows CMD
set MIRU_DEEPSEEK_API_KEY=sk-xxxxxxxx
set MIRU_PUSHPLUS_TOKEN=xxxxxxxxxxxx

# Git Bash
export MIRU_DEEPSEEK_API_KEY=sk-xxxxxxxx
export MIRU_PUSHPLUS_TOKEN=xxxxxxxxxxxx
```

### 使用

```bash
# 查看帮助
miru --help

# 环境诊断
miru doctor

# 测试运行（不推送）
miru run --dry-run

# 正式运行
miru run

# 查看状态
miru status

# 推送最新日报
miru push

# 查看微信群列表
miru groups

# 读取最近消息
miru read -n 20
```

## 生产部署

### 安装自动运行

以管理员身份运行 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_scheduler.ps1
```

安装后，每天 21:00 自动运行。无需任何手动操作。

### 管理定时任务

```powershell
# 查看任务
schtasks /Query /TN "Miru Assistant Daily Report"

# 手动运行一次
schtasks /Run /TN "Miru Assistant Daily Report"

# 卸载
schtasks /Delete /TN "Miru Assistant Daily Report" /F
```

### 查看日志

```
data/logs/
  miru_2026-07-24.log      # 每日日志
  run_2026-07-24.log        # 运行记录
  scheduler.log             # 调度器日志
```

## 微信准备

1. 在 PC 上安装并登录微信
2. 确保在微信中能看到你要监控的群
3. 微信保持运行状态（可以最小化到托盘）
4. 每天晚上 21:00 前不要关机

## DeepSeek 配置

1. 注册 [DeepSeek](https://platform.deepseek.com/) 账号
2. 获取 API Key
3. 设置环境变量 `MIRU_DEEPSEEK_API_KEY`
4. 建议充值 10 元（足够使用数年）

## PushPlus 配置

1. 注册 [PushPlus](http://www.pushplus.plus/) 账号
2. 获取 Token
3. 关注 PushPlus 微信公众号
4. 设置环境变量 `MIRU_PUSHPLUS_TOKEN`

## 常见问题

### Q: "微信未运行"错误

**答**: 确保微信 PC 客户端已启动并登录。Miru 需要读取微信的本地数据库。

### Q: "需要管理员权限"错误

**答**: Miru 需要管理员权限才能读取微信进程内存。以管理员身份运行终端，或使用任务计划程序自动运行。

### Q: 微信更新后 Miru 失效

**答**: 微信大版本更新可能改变加密方案。关注 GitHub 上的 `wechat-decrypt` 项目更新。更新后重新安装依赖即可。

### Q: 日报没有收到

**答**: 
1. 检查 `miru status` 查看运行状态
2. 检查 `data/logs/` 日志文件
3. 确认 PushPlus 已关注公众号
4. 测试 `miru push` 手动推送

### Q: DeepSeek API 调用失败

**答**: 检查 API Key、网络连接、账户余额。DeepSeek API 在国内可直接访问。

### Q: 可以在 Mac 上运行吗？

**答**: 当前仅支持 Windows。Mac 版微信的数据库加密方案不同，需要单独适配。

## 项目信息

- 语言: Python 3.11+
- 数据库: SQLite
- AI 引擎: DeepSeek V4 Flash
- 推送服务: PushPlus
- 许可证: MIT
