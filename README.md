# Miru Assistant

这是一个按产品划分的 monorepo。仓库里有两套用途不同、但会复用部分微信分析能力的应用。

## 产品目录

```text
products/
├── mobile-assistant/          # 当前主力：手机语音 AI 助手
│   ├── app/                   # Flutter 客户端
│   ├── server/                # FastAPI、STT、LLM、TTS、Memory、Tool
│   └── docs/                  # 架构与协议文档
└── daily-report/              # 已暂停日常使用：微信日报与聊天分析
    ├── src/miru/              # Python 包
    ├── scripts/               # 日报、导出、分析与运维脚本
    ├── config/                # 配置模板与本机私有配置
    ├── tests/                 # 单元测试
    ├── docs/                  # 架构、指南、运维和历史发布资料
    ├── data/、output/         # 本机运行数据与分析结果（不入 Git）
    └── tools/                 # 第三方微信数据工具（不入 Git）
```

## 从哪里开始

- 手机助手总览：[products/mobile-assistant/README.md](products/mobile-assistant/README.md)
- Flutter 客户端：[products/mobile-assistant/app/README.md](products/mobile-assistant/app/README.md)
- 手机助手后端：[products/mobile-assistant/server/README.md](products/mobile-assistant/server/README.md)
- 日报/聊天分析：[products/daily-report/README.md](products/daily-report/README.md)
- 日报文档索引：[products/daily-report/docs/README.md](products/daily-report/docs/README.md)

## 项目边界

手机助手是当前应优先维护的产品。它的后端可以独立运行；只有启用微信查询工具时，才会可选导入日报项目中的 `miru.chat_analyzer`。日报项目目前保持独立，以便以后单独维护、停用或抽取共享包。

根目录的 `venv/` 是迁移前留下的共享虚拟环境，现有启动脚本仍会把它作为兼容回退。后续新环境建议在各 Python 项目内创建自己的 `.venv/`，避免依赖互相污染。

## 常用命令

```powershell
# 手机后端
cd products/mobile-assistant/server
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt -e .
.\.venv\Scripts\python -m miru_server

# 日报/聊天分析
cd products/daily-report
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
```

CI 的 iOS 构建配置仍放在仓库根目录：[codemagic.yaml](codemagic.yaml)。许可证见 [LICENSE](LICENSE)。
