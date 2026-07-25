# GEO 非 B 能力运维手册

本手册覆盖当前路线图的 A（合成与知识）、C（观测与统计）和 D（Prompt 与建议）能力。
Connector Core、GSC/GA4、官方报告、澳洲代理/Browser Capture 和归因账本属于 B，本手册既不
启用它们，也不把手工工件或 fixture 写成真实采集证据。

## 1. 发布前门禁

候选提交、镜像 digest、Alembic head、两份稳定 OpenAPI、两个 Web build、Prompt/Adapter
Release、性能 profile/workload 和本次变更记录必须先冻结。依次执行：

```bash
make quality
make test-migrated
make openapi-contracts
make web-contracts
make web-build
make test-browser-chromium
make test-infra-contracts
make test-infra-runtime
```

任何零收集、意外 skip、失败、未解释的 OpenAPI diff 或明文扫描发现都阻断发布。真实
Provider、模型、风格渠道、production network、30 分钟性能和独立 verifier 证据必须在最终
manifest 中单列；本地测试不能替代。

真实或敏感数据进入候选环境前，按[备份与恢复](backup-restore.md)完成当期认证备份和空环境
恢复。恢复必须覆盖 PostgreSQL、五个 MinIO bucket、历史 Secret/Provider/Synthetic/
Recommendation/Workflow C keyring、代表性解密和错误/缺失 key 负测。

## 2. 部署和数据库切换

没有经过兼容性演练的迁移继续使用[生产部署](production-runbook.md#7-升级与回退)的维护窗口
原子升级。只有满足以下全部条件的 additive 迁移才可使用在线切换：

- writer inventory 已冻结，旧/新 writer 均为 compatible writer；
- 数据库 trigger 或应用双写在同一事务中写入旧、新投影，任一侧失败整体回滚；
- initial backfill 后按单调 watermark 追尾，dual-read 只用于对账而不承担同步；
- cutover lock 能阻止并发切换，连续两轮逐 scope `difference_count=0` 且 `lag=0`；
- rollback window 继续双写并保留旧读路径，旧 writer 退役后才允许 contract。

先在隔离 PostgreSQL 生成并验证收据：

```bash
make roadmap-migration-cutover-rehearsal \
  GEO_MIGRATION_REHEARSAL_DATABASE_URL="$ISOLATED_DATABASE_URL" \
  OUTPUT="artifacts/migration-cutover/$RUN_ID/receipt.json"
make roadmap-migration-cutover-verify \
  RECEIPT="artifacts/migration-cutover/$RUN_ID/receipt.json"
```

生产执行必须使用当期真实 writer、Project/Campaign 和 watermark，不能复用本地随机 schema
收据。切换后若出现差异、lag、旧 writer 写入或 lineage/hash 不一致，立即恢复旧读路径；在
rollback window 内保持双写并前向修复。已经有新写入时不得只 downgrade schema 或只回退
镜像。

## 3. Prompt 和模型变更

Prompt Program 只通过 create -> fixed-input test/diff -> submit -> independent approve -> freeze
-> bind 发布。禁止原地编辑已冻结 Release。回退时把用途重新绑定到已验证的旧 frozen Release，
保留失败 Release、模型身份、输入版本、调用日志和变更原因；不要删除历史 lineage。

模型或 Adapter 变更先创建新 Release，冻结结构化输出 schema、模型标识、存储/保留/展示
条款、预算和 Secret Reference version。每个 Provider 独立执行 canary，不能用另一 Provider
的成功补足。无有效 release、secret、预算、授权或 reported-model 不符时保持 fail closed，
禁止静默 fallback。

Provider Secret 轮换顺序固定为：创建新 version -> 在不输出明文的 test/canary 中验证 ->
切换新命令引用 -> 等待旧 lease/Job 结束或取消 -> 撤销旧 version -> 扫描 Job/outbox/log/API/
artifact。运行中的命令始终使用已冻结 reference version；不得让“latest”在重试时改变凭据。

## 4. Sampling、统计和告警

故障处置必须保留原 Task 分母。重试只创建新 Attempt；实际 location/egress verification 只写
Attempt/Observation lineage，不能进入 Task identity 或拆分 SourceStratum。Provider API、
proxy grounded API、manual UI、automated UI、official report 和 synthetic 永不混合分母。

出现以下情况时停止消费结果并检查 frozen Protocol、Observation 和 artifact：

| 现象 | 处置 |
|---|---|
| 有效完成度低于 80% 或样本不足 | 输出 `insufficient_evidence`，不得给方向性结论 |
| 区间跨过正负 practical threshold 且精度/功效不足 | 输出 `inconclusive`，不得标为“平”或等效 |
| reported model、citation、source 或 schema 漂移 | 隔离对应 Release；不影响其他 source 的分母 |
| lease 丢失、Worker 终止或 broker 中断 | 等待 lease 到期后 fenced reclaim；旧 lease 禁止终结 |
| MinIO 部分写入 | 先记录受控失败/crypto-erasure，再由 maintenance Job 幂等清理 |

Alert 先由运营人员确认，再选择抑制或解决；所有动作保存 actor、时间、原因和 aggregate
version。抑制只影响通知，不删除触发事实。SMTP/Webhook 重试复用同一 notification identity，
不得新建第二张业务告警；Webhook 签名或目标配置错误时保持 Admin Inbox 可见并升级处理。

## 5. 合成实验室和受限工件

真实风格渠道只有在版本化 authorization record 为 `approved` 且未过期/撤销时才能 enqueue。
验证码、challenge、封禁、限流或条款阻断立即停止，不做代理轮换、stealth 或绕过。登录凭据
只能使用 Secret Reference。

Raw 工件在落盘前完成 secret/PII 分类和清理，分别进入 Synthetic raw/derived 或 Workflow C
受限 bucket；普通 Admin/Customer/API 响应只返回允许的摘要和 hash。删除顺序为 DEK
crypto-erasure -> payload/manifest 删除 -> tombstone。部分删除可重试，但不得重复销毁 DEK。

Legal hold 使用 maker/checker 的 apply/extend/release 生命周期，最长 90 天。到期 maintenance
只处理当前 Project 和当前 hold version；未批准或过期请求不能阻止依法保留策略执行。Customer
永远不能读取 synthetic、manual UI、raw、内部建议、actor/debug 或未批准/stale/revoked 结果。

## 6. Recommendation 失效和回退

Recommendation 审批只允许创建未开始的 Experiment Plan、QuestionSet、Content Brief 或
Sampling Plan 草稿。Fact、Observation、统计方法、Prompt 或批准来源失效时追加 `stale`/
`expired` 版本，原子阻断未开始草稿并取消未投递 outbox。已经开始的任务不改写历史，但必须
停止后续自动步骤并升级人工处置。任何草稿执行前都重新锁定并校验原 approved version；
repository、Worker 和 API 均不能旁路。

B 被排除期间 Attribution 必须明确为 `unavailable`，不得用 GA4 聚合、人工值或概率关联补造。

## 7. 故障、恢复和证据

本地可重复的故障矩阵使用 `make roadmap-non-b-fault-contracts`；带隔离 PostgreSQL/Valkey/
MinIO 的运行使用 `make roadmap-non-b-fault-runtime` 并保存 mode `0600` 的 receipt。生产事故
至少记录 release/commit、Project、Job/Attempt、lease/fence、非敏感错误码、开始/结束时间、
处置和恢复验证，不记录 Prompt/答案、URL query、headers、Cookie、secret 或 raw artifact。

发布证据至少包含：Git commit、single Alembic head、OpenAPI/双 Web build hash、测试执行/
失败/skip 数、迁移/故障/恢复/性能 receipt URI 与 SHA-256、Prompt/Adapter/Profile/Protocol
Release、人工审核、偏差和成本。Owner 不能验证自己的证据；缺独立 verifier 时状态保持
`BLOCKED_EXTERNAL`，不能标记 `ACCEPTED`。

以下项目统一留到最终外部请求，不阻塞继续完成本地工作：真实模型和五 Provider 凭据/预算、
九渠道样本与审核人员、production-equivalent staging、30 分钟完整性能运行、历史 key escrow
保管人、独立 verifier。B 所需的连接器账号、澳洲 sticky egress、Browser Capture、官方报告和
归因真实旅程继续按独立专项计划处理。
