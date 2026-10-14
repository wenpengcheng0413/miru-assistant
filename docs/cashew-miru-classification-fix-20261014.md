# Cashew 普通账单被误排除与前台刷新修复

代码提交：`586f43c`；Miru 客户端：`0.3.4+7`；Cashew 继续使用 `5.4.3+418`。

## 原因

Cashew `addTransactionPage.dart:createTransaction` 对普通账单默认设置
`paid=true`、`skipPaid=true`、`type=null`。其统计使用 `paid` 判断实际收支，
付款状态 UI 也优先判断 `paid`。因此不能直接把 `skipPaid=true` 理解成用户跳过了账单。

之前 Miru 在判断 paid 之前排除了所有 skipPaid 记录，造成已成功同步的普通账单仍显示“已跳过”，
汇总 currencies 为空。聊天回复进一步把这个技术标志推断成用户手动批量操作，属于无依据推断。

## 修正行为

- 查询层只将未支付、带 skipPaid 标志的 upcoming/subscription/repetitive 记录归为跳过。
- 普通已支付记录、已经支付的周期记录正常计入收入或支出。
- 同一规则用于汇总、逐笔、状态筛选和 AI 查询工具；原始上传记录不修改。
- 工具说明要求使用当前查询结果，不沿用旧聊天里的空汇总，不推断用户做过批量操作。
- 若带恢复标志的上传与当前五组账本数据完全一致，允许接收；真正变化的恢复仍需核对。
- 线上已有的待核对上传经逐项比对完全一致，已通过原有接收流程确认，未修改任何金额、日期或备注。

## 前台同步体验

Cashew 418 已监听本地数据库变化，约 3 秒后发起同步，前台每 30 秒补查；
不承诺关闭 App 后持续上传。LiveContainer 用户应在 Cashew 显示同步完成后切换。

Miru 0.3.4+7 打开账本时读取最新数据，回到前台时检查服务器版本，账本页可见时每 10 秒检查。
版本不变不重新加载列表，以保留滚动位置；后台或弹出其他页面时暂停检查。
聊天每次查询从服务器读取最后成功同步的数据。

## 验证与部署

- 17 项 finance 测试通过，包括普通账单 skipPaid、真实跳过、已支付周期账单、相同/不同恢复、权限和金额精度。
- Flutter 全部 12 项测试通过，包括前后台切换、前台版本变化、未变化不重载。
- finance 页面及测试静态分析无问题。
- 云端只覆盖 `finance/store.py`、`tools/builtin/finance.py`，基于旧生产镜像构建，其他功能与配置保留。
- 发布：`miru-cloud:cashew-finance-classification-20261014`。
- 发布前完成数据库和附件备份，并以只读方式核验生产账本的修正结果。
- 回滚目标记录在新发布目录的 `rollback-target.txt`，数据库结构不变。
- HTTP 汇总、逐笔和聊天工具输出已核验；详细用户数据仅留在本机验证文件，不提交仓库。

## 安装

统计修复已在服务器生效，旧 Miru 刷新也能读取正确结果，无需重新配对。
自动刷新需要在原 LiveContainer 容器覆盖更新 Miru 0.3.4+7；保留原容器及设置。
构建：[Codemagic #70](https://codemagic.io/app/6a7d2b2285432d3d8f060eea/build/6acf3ff1a90f016d29d0d5c3)。

构建成功，用时 5 分 20 秒。本机 IPA 完整性校验通过，版本 `0.3.4`、build `7`、
应用标识 `com.miru.miruApp`，共 9,517,620 字节。SHA-256：
`96f0d20a029bada3a840fdf528edfafb8882e64c2a52d090fadfdb972137c673`。
