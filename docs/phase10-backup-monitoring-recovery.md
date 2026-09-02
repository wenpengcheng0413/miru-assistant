# Phase 10 备份、监控与恢复实施记录

日期：2026-09-02

状态：本地实现与回归已完成第一批；尚未安装离机备份工具、授权第三方账号或激活生产配置。

## 目标与边界

- 每天使用 SQLite Backup API 生成一致性快照，保留 14 个日备份和 8 个周备份。
- 每个数据库快照都经过 `PRAGMA integrity_check`、SHA-256、schema 版本和安全行数校验。
- 同步生成附件完整性清单；清单只记录相对路径的哈希、文件哈希和字节数，不记录文件名、聊天正文或绝对路径。
- 恢复只能写入一个不存在的新暂存目录。程序不提供覆盖生产卷或自动切换 `current` 的入口。
- `/api/status` 只暴露聚合备份状态、磁盘占用、进程 RSS、Swap 和负载，不暴露路径、文件名或内容。
- 磁盘达到 70% 标记 warning、85% 标记 restricted、90% 标记 critical；90% 时拒绝新附件但继续文字聊天。
- 附件另有 10GB 软配额，超过配额只关闭新附件入口。

## 已实现内容

- `db/backup.py`
  - 临时文件写入、完整性检查后原子改名。
  - 日备份和 ISO 周备份独立轮换。
  - 数据库和附件清单的内容无关验证。
  - staging-only 恢复及恢复后二次校验。
- `scripts/backup_admin.py`
  - `create`、`verify`、`restore` 三个操作员命令。
  - 成功只输出聚合 JSON；失败只输出固定错误码。
- `operations.py` 与 `/api/status`
  - 提供安全的容量、内存、Swap、负载和最近备份状态。
- 附件入口
  - 10GB 软配额与 90% 磁盘保护。
  - 触发保护时使用 HTTP 507，文字聊天和历史读取不受影响。

## 免费优先的离机副本

首选方案是 `restic + rclone + Google Drive`：restic 在上传前完成客户端加密和去重，rclone 只负责传输密文。Google 官方说明普通 Google 账号提供最多 15GB 免费空间，但该额度与 Gmail、Google Photos 等共享，因此启用前必须先读取实际剩余空间；空间不足时停止配置，绝不自动订阅 Google One。

备选方案是把同一 restic 加密仓库保存到用户现有 Windows PC 或外接硬盘，不连接第三方云盘。它没有新增订阅费用，但只有设备在线时才能完成离机复制。

生产启用离机副本前必须单独取得授权，因为届时会：

1. 在腾讯云主机安装 restic/rclone；
2. 创建 Google OAuth 持久访问或配置用户指定的本地目标；
3. 将加密后的数据库与附件副本传输到该目标。

restic 仓库密码必须存放在 `/opt/miru/secrets/` 的 root-only 文件中，不能进入仓库、日志、命令参数或聊天。丢失该密码将无法恢复备份。

## 生产激活顺序

1. 只读确认当前 release、数据库 integrity、磁盘/Swap、容器重启次数和备份目录权限。
2. 创建激活前 SQLite Backup API 快照，不复制 WAL/SHM 原文件。
3. 构建只包含 Phase 9 断线保护与本 Phase 10 文件的 overlay 镜像。
4. 以新 release 启动候选，验证 `/healthz`、`/readyz`、`/api/status.operations` 和数据库完整性。
5. 等待应用生成首个日备份，使用 `backup_admin.py verify` 校验。
6. 从该备份恢复到全新暂存目录，确认会话行数、schema、附件 manifest 和哈希一致。
7. 仅在全部通过后切换当前 release；失败则恢复旧 release，并保留候选和原数据用于诊断。

## 尚未完成

- 生产 overlay 构建、传输和激活。
- 加密离机仓库初始化及第一次 `restic check`。
- systemd 定时任务、失败告警和一次完整离机恢复演练。
- 85% 水位下非必要预览停止策略。
- Token 撤销、SQLite corruption、容器重启和磁盘 85%/90% 演练。

## 本地验证

- 服务端完整回归：148 passed，1 skipped（仅沙箱 DPAPI）。
- Phase 10 新增模块 Ruff 校验：通过。
- JSON/YAML 配置解析：通过。
- 备份篡改、清单隐私、轮换、暂存恢复、磁盘阈值和操作员 CLI 均有自动化覆盖。

## 参考

- [Google Drive 免费存储说明](https://support.google.com/drive/answer/2375123)
- [restic 仓库与 rclone 后端](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html)
- [rclone Google Drive 后端](https://rclone.org/drive/)
