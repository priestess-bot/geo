# GEO v3 运行与验收合同

> 状态：当前产品基线与交付验收合同
>
> 适用版本：GEO v3 及其兼容修订
> 操作细节：[GEO 全流程操作手册](operations/geo-full-flow-runbook.md)

## 一、产品目标

GEO v3 面向通用商品和服务场景：记录消费者在 ChatGPT Search、Google 等 AI/搜索界面的真实问题与回答，分析品牌提及、推荐和引用来源，为 AI 工具可能参考的网站建立投放任务，生成符合各渠道规则且证据可追踪的内容，经人工审核、人工发布、公开 URL 验证后，用冻结口径持续复测。

系统不承诺任何模型一定推荐某品牌，也不把观察到的变化直接解释为投放因果。系统不自动登录 ProductReview、YouTube、Reddit、Amazon、OzBargain、TikTok、Instagram、Quora 或其他第三方平台，不保存这些平台的账号密码，不自动发帖或购买广告。

```text
消费者问题
-> 基线观察与引用
-> 渠道目的地及政策
-> 投放机会
-> Evidence + independently editable Prompt
-> DeepSeek 渠道文案
-> Claim QA + maker-checker review
-> 可选导出
-> 显式投放请求
-> 人工第三方发布
-> URL 回填与验证
-> T+28 / T+56 / T+84 复测
-> 客户只读报告
```

## 二、当前部署合同

| 部署单元 | 本地入口 | 职责 |
| --- | --- | --- |
| Admin Web | `http://localhost:3001` | 内部配置、监测、生成、审核和投放管理 |
| Customer Web | `http://localhost:3000` | 客户只读指标、验证 URL 和已批准报告 |
| Internal API | `http://localhost:8000` | 内部稳定读写 API |
| Customer API | `http://localhost:8001` | 独立进程、最小权限客户投影 |
| `geo_worker` | 无公网入口 | Evidence、Prompt Artifact、DeepSeek 生成、导出、URL 验证、测量窗口任务 |
| Outbox Relay | 无公网入口 | 从 PostgreSQL Outbox 唤醒 Worker |

PostgreSQL 是业务状态和 Durable Job 真源；Valkey/Dramatiq 只传递唤醒信号；MinIO 保存不可变工件；DeepSeek Key 只挂载给 Worker。API 返回 `202 + job_id + status_url` 后，操作者通过 `/v1/jobs/{job_id}` 或界面任务状态等待完成，不进行同步模型调用。

## 三、角色与职责

当前内部 RBAC 为 `owner`、`admin`、`analyst`，客户只读身份由 Customer Invitation 与 Session 管理。Content Operator 和 Reviewer 是工作职责，不是额外数据库角色。

| 身份 | 主要能力 |
| --- | --- |
| Owner | 项目和成员治理、目的地政策复核、发布授权、全部内部操作 |
| Admin | 日常成员治理、目的地政策复核、发布授权、全部业务操作；不能管理 Owner |
| Analyst | Catalog、监测、Brief、Prompt、生成、编辑、提交审核和测量；不能执行 Owner/Admin 发布权限 |
| Customer | 只读查看授权项目的指标、测量窗口、已验证 URL 和已批准报告 |

同一个内部角色可以承担提交或审核职责，但同一 Package Version 的 `submitted_for_review_by` 与 `reviewer_id` 必须是不同身份。不能用共享账号通过 maker-checker 门禁。

## 四、九渠道任务合同

一个 Campaign 选择的每个渠道都必须产生独立 Destination 和 Opportunity。政策未审核、身份不合格、证据不足或渠道禁止品牌行为时，任务仍需持久化并显示 `blocked`/未资格原因，不能静默丢弃，也不能伪造为可发布。

| `publication_channel` | 合规任务示例 | 不允许伪装的行为 |
| --- | --- | --- |
| `owned_site` | 官方产品页、FAQ、比较页 | 伪造第三方背书 |
| `amazon` | 已授权卖家 Listing/A+ 内容 | 冒用商品或卖家身份 |
| `youtube` | 官方视频脚本、说明、创作者 Brief | 隐瞒付费或品牌关系 |
| `tiktok` | 官方/授权短视频脚本 | 未披露商业关系 |
| `instagram` | 官方/授权 caption 与素材 Brief | 未披露商业关系 |
| `productreview` | 商家资料、合规官方回复任务 | 伪造消费者评价 |
| `reddit` | 明确品牌身份的官方参与任务 | 假装普通用户或刷帖 |
| `ozbargain` | 真实优惠且身份合规的提交任务 | 虚假优惠、隐藏商家关系 |
| `quora` | 明确关系的专业回答任务 | 虚构独立体验或专家身份 |

Destination 保存具体 URL/账号、`destination_key`、`destination_account_id`、运行模式、允许 Host，以及不可变政策复核版本。`operation_mode=manual` 表示系统只管理任务和内容，发布由人完成。

## 五、真实性与证据合同

允许直接提供一段真实消费者使用描述，作为 `consumer_experience` Evidence 保存。最低字段是：原始描述、来源、使用/改写权利、必须展示的披露。系统不要求建立复杂体验者档案，但必须保留原始描述的 snapshot/hash，生成内容不得超出其原意和授权边界。

以下风险不可 override：

- `synthetic_testimonial`：合成或伪造评价；
- `fake_persona`：虚构消费者或专业身份；
- `unsupported_first_person_experience`：没有真实输入支持的第一人称体验；
- `hidden_commercial_relationship`：隐瞒品牌、商家、付费或赠品关系。

“允许上传给模型”和“允许公开改写”不自动证明体验真实。`usage_rights=unknown/restricted`、非公开机密数据或缺少主体绑定的事实必须 fail closed。

Evidence Item 使用判别类型，保存 subject、snapshot/hash、source revision、usage rights、confidentiality 和公开 Citation 权限。内部 Evidence 与公开 Citation 分开：内部可追踪不代表可以在网页上公开引用。

Evidence Pack 为不可变 Attempt：

```text
Attempt 1: needs_evidence
Attempt 2: blocked
Attempt 3: ready
```

旧 Attempt 永不重新进入 `building`。`needs_evidence` 表示补充事实可恢复，`blocked` 表示权限、保密、授权或政策阻断。

## 六、Prompt 与流程解耦合同

提示词不硬编码在 Campaign、生成 Job 或 Worker 流程中：

```text
editable Skill source
-> immutable Template Release
-> project/channel Task Binding
-> frozen Prompt Bundle
-> Generation Job
```

每个项目可独立安装九渠道默认 Prompt，也可发布自定义 Release 并切换指定 `task_key`。安装默认目录是收敛操作：只补缺失绑定，不覆盖用户已经选择的自定义 Release。

Release hash 必须覆盖源码、编译模板、变量 schema、输出 schema 和编译器版本。Prompt Bundle 固定 Brief Version、Evidence Pack Attempt、Release、变量、模型策略和工件 hash。修改提示词不修改工作流状态机，也不能绕过证据、真实性、披露、账号、审核或发布门禁。

## 七、生成与 Job 合同

GEO v3 默认配置模型为 `deepseek-v4-flash`。每次请求创建 PostgreSQL Durable Job；Worker 在外部模型调用前冻结输入并释放数据库事务，调用结束后在新事务中用 lease、fencing generation 和幂等键校验结果。

Job 规则：

- `succeeded` 表示模型输出已经持久化；Package 后续 QA 阻断不把 Job 改成部分成功。
- `retry` 重用同一 Job 和输入；`replay` 创建新 Job 并指向旧 Job；重新生成使用新 nonce/幂等键。
- 模型调用、Schema 修复和 fallback 共享 `model_call_budget`，避免重试层数相乘。
- Worker 崩溃后可接管租约过期任务；旧 Worker 的迟到结果被 fencing 拒绝。
- PostgreSQL 结果与 Job 完成必须同事务；MinIO 使用 pending artifact + finalize/outbox。

模型调用日志保存 provider request ID、configured/reported model、token、cost、finish reason 和 response hash，不保存 API Key 或完整敏感 Prompt/正文到通用 HTTP 日志。

## 八、Package、Claim 与审核合同

Placement Package Version 的工作流状态只描述内容本身：

```text
generated
-> qa_running
-> pending_human_review
-> approved | needs_revision | rejected | blocked
-> archived | superseded
```

Export、Delivery 和 Publication 状态不进入该状态机。人工编辑必须基于精确 `base_version_id + base_content_hash` 创建新版本，写入编辑者和原因；旧版本保留并标记 superseded，新版本重新执行 Claim 抽取、QA 和审核。

批准必须同时满足：

- `claim_inventory_complete=true`；
- `extracted_claim_support_confirmed=true`；
- 没有 unsupported Claim；
- 主体归属、公开 Citation、披露、CTA、链接和渠道规则通过；
- Reviewer 与提交人不同；
- `score >= 85`。

`evidence_coverage_ratio=100%` 不能替代 Claim inventory 完整性确认，避免漏抽取事实句后绕过门禁。

## 九、导出、投放和验证合同

```text
approved Package Version
-> optional Export
-> explicit Publication Request
-> manual third-party action
-> Submission
-> URL backfill
-> Verification Job
-> measurements
```

Export 只产生可下载工件和 Export Receipt。它不创建 Publication Request、Submission、待回填 URL、投放 KPI 或测量窗口。

只有 Owner/Admin 显式点击“创建投放请求”或调用 `POST .../publication-requests`，系统才保存发布意图。同一 Package Version 可以面向同平台的不同账号、地区或多次合法投放；`publication_attempt` 区分业务尝试，`Idempotency-Key` 防止重复点击。

运营人员必须离开系统，在已授权第三方账号中人工发布。回到 Admin 后创建 Submission 或回填真实公开 URL。Verification Worker 只允许 Destination 的 allowlisted Host，并阻断内网、重定向逃逸和 SSRF；验证页面可达性、内容、披露和链接。失败结果不能计入已验证覆盖。

## 十、监测、测量与报告合同

每个 Monitoring Protocol 固定 Campaign、市场、平台、locale、设备、样本数和窗口。Query Suggestion 经批准后成为监测 Query；Protocol 先批准再冻结，冻结后不能原地改口径。

Observation 保存每个原始样本，而不是只保存汇总分：原始回答/结果、引用 URL、样本序号、configured/reported model、UI surface、时间、工件 hash、eligibility 和 confounding factors。

基线与复测使用同一冻结协议。URL 验证成功后创建 T+28、T+56、T+84 窗口。指标至少包含 recommendation share、product mention share、placement citation share、qualified destination coverage、verified placement coverage 和 competitive delta。

有模型、界面、价格、库存、季节、竞品或商品版本变化时标记 `confounded`。报告必须显示方法和限制；只有已批准报告对 Customer API 可见。

## 十一、客户权限合同

客户用一次性 Invitation 在 Customer Web 兑换 HttpOnly Session Cookie。Session 保留同租户全部有效项目 membership，不把本次邀请项目错误地当成唯一项目。Customer API 只提供：

- `/v1/auth/me`；
- `/v1/projects`；
- 项目级 `summary`、`metrics`、`measurement-windows`、`verified-urls`、`reports`。

Customer API 不注册 Prompt、Evidence 原文、未批准 Package、Job、成员、审计、Dev Tools 或 Engineering 路由。客户只能看到已验证 URL 和已批准报告。

## 十二、运行截图证据

本文件不使用旧运行图片冒充当前验收。浏览器验收完成后，真实截图写入 `docs/operations/images/`，并在全流程手册的对应步骤登记 commit、运行 ID、视口和截图路径。截图必须来自当前稳定路由，控制台无错误，且包含桌面、平板、移动视图。

## 十三、最终通过标准

以下项目必须在同一个可追溯运行 ID 下闭合：

1. 空数据库和空对象存储执行 Alembic 后完整栈健康；
2. OIDC 首个 Owner、内部成员与客户 Invitation 流程通过；
3. 一个真实商品建立 Campaign、冻结 Monitoring Protocol 并导入基线样本；
4. 九个渠道全部有 Destination 和 Opportunity，阻断渠道显示真实原因；
5. Evidence Pack、Prompt Release/Binding/Bundle lineage 可追踪；
6. `deepseek-v4-flash` 实际生成至少一份具体渠道文案，非 fixture、非手填伪结果；
7. Claim inventory 与逐 Claim 支撑通过两个不同身份审核；
8. 人工编辑创建新版本且旧审批失效；
9. Export 前后 Publication Request 数量不变；
10. 显式 Publication Request、人工 Submission、URL 回填和成功/失败 Verification 均有记录；
11. T+28/T+56/T+84 待办或结果使用冻结口径；
12. Customer Web 只显示授权项目的已验证/已批准投影；
13. 跨项目访问、同人审批、无证据生成、SSRF URL、重复消息和租约接管负向测试通过；
14. PostgreSQL + MinIO 备份完成，隔离恢复冒烟通过；
15. Admin/Customer 桌面、平板和移动浏览器验收通过，截图和控制台证据归档。

缺少任一必需证据时，只能报告对应阶段已完成，不能宣称 GEO v3 全流程完全可用。第三方平台没有实际发布时，必须明确写“系统内投放链路已验收，外部发布待人工执行”，不能用本地页面或 fixture 冒充公开投放。
