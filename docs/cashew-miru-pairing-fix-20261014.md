# Cashew 418：首次同步失败与配对提示修复

用户在 LiveContainer 中一次只能打开一个 App。反馈从 Miru 复制配对码、切换到 Cashew 后提示配对码过期，截图同时显示自动同步已开启。

## 排查证据

仅查询同步状态，未读取或导出账单内容。线上返回 `state=awaiting_sync`、`paired=true`、`revision=0`、`synced_at=null`。说明服务端已经接受配对，首次账本尚未发布；关闭 Miru 不会撤销服务器上的配对码或上传凭据。再次提交已兑换的一次性码会被拒绝，这是用户看到“过期或已使用”的原因。

Cashew Drift 生成的 `TransactionWallet.toJson()` 保留 `List<HomePageWidgetDisplay>`，`Budget.toJson()` 保留 `List<BudgetTransactionFilters>`。Drift 默认序列化器只转换 DateTime，对上述列表返回原对象。因此，旧版对含这些字段的账本执行普通 `jsonEncode(data)` 时，在发起上传请求前就会抛出 `JsonUnsupportedObjectError`。旧版把它归为普通同步错误，且未区分“已配对”和“未上传成功”。

在使用 Drift 实际默认序列化器的合成回归样例中复现了此失败。未取得手机端错误堆栈，所以本地复现用于确认代码缺陷；最终仍需更新后用用户手机验证。

## 修复

- 提交 `3504c29`，Cashew `5.4.3+418`，仍在 `codex/miru-finance-sync` 分支。
- 共用 JSON 编码函数将嵌套枚举转换成名称；快照内容哈希和 HTTP 传输使用同一种编码。保留原金额、备注等字段，不能编码的未知对象仍整体拒绝。
- 已保存上传凭据时明确显示“已配对”，默认隐藏一次性码表单；重新配对需要主动展开。
- “立即同步”清除之前的操作错误。自动同步开关以已保存的凭据判断可用性，而非只看服务器地址。
- 页面说明 LiveContainer 可以先关闭 Miru 再打开 Cashew，配对码在服务器上保留十分钟，不要求同时运行。
- 不改数据库、生成文件、依赖版本、服务器鉴权、配对码有效期或 Miru 客户端。

## 验证与安装

协议回归检查通过；修复模块静态分析无问题；完整 `flutter analyze --no-pub` 无错误，225 条原有警告/提示保持不变。

[Codemagic #21 构建页](https://codemagic.io/app/6a106336e948beff964378b5/build/6acf04f312cce3cb996488c3)。构建成功后在 Artifacts 下载 Runner.ipa。只更新 Cashew，使用原来的 LiveContainer 容器覆盖更新，保留本地账本与安全存储。更新后打开“米汝同步”，显示“已配对”时直接点“立即同步”；不要再使用旧配对码。成功上传后关闭 Cashew，再打开 Miru 刷新账本。

状态：Codemagic #21 已成功（6 分 57 秒），IPA 已下载到 `data/finance-build/Cashew-5.4.3-418.ipa`；ZIP 完整性通过、包内 build 为 418、应用 ID 仍为 `com.budget.tracker-app`。实际手机上传待更新后验证。
