# Miru Assistant — CLI 重构计划 (V2)

## 当前状态 (V1)

`src/miru/cli/main.py` — 884 行，包含所有 CLI 命令。

## V2 目标结构

```
src/miru/cli/
├── __init__.py
├── main.py              # Typer app 定义 + callback (轻量，约 40 行)
├── commands/
│   ├── __init__.py
│   ├── run.py           # miru run (含 --dry-run)
│   ├── doctor.py        # miru doctor (微信环境诊断)
│   ├── status.py        # miru status (健康检查面板)
│   ├── push.py          # miru push / miru push --retry
│   ├── config.py        # miru config (validate/show/init)
│   ├── groups.py        # miru groups (微信群列表)
│   └── read_msgs.py     # miru read (读取消息)
└── formatting.py         # 共享格式化 (banner, status icons, tables)
```

## 迁移步骤

1. 创建 `cli/commands/` 目录和 `__init__.py`
2. 逐个提取命令函数到独立模块
3. `main.py` 从各模块 import 命令并注册到 app
4. 提取公共格式化函数到 `formatting.py`
5. 保持 `miru` CLI 接口完全向后兼容

## 影响评估

- **无功能变更** — 仅移动代码
- **测试无需修改** — CLI 接口不变
- **风险极低** — 纯重构

## 时间计划

V2.0 初期执行。约 2-3 小时。
