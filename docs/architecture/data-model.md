# 数据模型与不变量

## 租户隔离

所有项目拥有对象必须包含 `project_id`。项目内引用使用 `(id, project_id)` 复合外键，同时启用 PostgreSQL RLS。RLS 负责可见性，复合外键负责关系正确性，两者不能互相替代。

身份由 `(issuer, subject)` 唯一标识；`project_memberships` 是项目授权真源。
`customer_sessions` 只保存 SHA-256 token hash、identity、tenant、期限和撤销状态，
不保存原始 token 或项目快照。RLS 使用事务局部的 identity、tenant 和 project ID
数组，因此一个 Session 可以保留同一租户内的全部有效项目，同时不能访问未授权项目。

owner/admin 管理他人 membership 时，应用角色守卫与 PostgreSQL RLS 同时生效；RLS 的
`SECURITY DEFINER` 判定函数固定 search path、关闭 PUBLIC/worker/readonly 执行权限，
并且仍核验事务 tenant 与数据库中的 active manager 关系。项目行锁串行化角色变更和
撤销，保证并发请求不能同时绕过最后 owner/manager 约束。`membership_commands` 保存
幂等 key hash、请求 hash 和冻结结果，不保存 raw key。

## 不可变版本

Brief、Evidence Pack、Template Release、Prompt Bundle 和 Placement Package Version 创建后不可原地修改。编辑创建新版本，保存 `base_version_id`、基础 hash、编辑者和原因；旧版本标记 superseded，但旧审核、投放和测量记录不删除。

Evidence Pack 的失败重试创建新 Attempt。`needs_evidence` 表示补充事实后可恢复，`blocked` 表示权限、机密、授权或政策阻断。

## 文案审核

审核至少包含 Claim inventory completeness 和每个已抽取事实 Claim 的证据支持结论。Claim 与 Evidence 是多对多关系；没有证据的 Claim 可以保存，但必须阻断批准。

消费者使用体验允许保存一段真实描述，同时记录来源、使用授权、公开披露和引用限制。系统不强制复杂的体验者档案；虚假证言、虚构身份、无依据第一人称体验和隐瞒商业关系仍不可 override。

## 发布边界

Export、Delivery、Publication Request、Submission 和 Verification 是不同实体或事件。一个版本可以向同一平台的不同账号、地区或多次尝试发布；幂等键防止重复点击，业务唯一约束不能禁止合法重复投放。
