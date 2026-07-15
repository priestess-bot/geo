# GEO 全流程操作手册

本文档既是操作手册，也是最终产品验收合同。只有本手册所有步骤在空项目中成功完成，系统才可标记“可交付”。迁移期间的真实状态以 [整改执行状态](../engineering/remediation-status.md) 为准。

## 流程图

```mermaid
flowchart TD
  A[创建项目和商品] --> B[导入公开来源与事实]
  B --> C[创建 Campaign 与消费者问题]
  C --> D[采集 AI 回答和引用]
  D --> E[选择目标网站与投放机会]
  E --> F[创建 Brief 和 Evidence Pack]
  F --> G[冻结 Prompt Bundle]
  G --> H[DeepSeek 生成渠道文案]
  H --> I[Claim QA 与人工审核]
  I -->|需修改| J[创建新版本]
  J --> H
  I -->|批准| K[显式创建投放请求]
  K --> L[人工投放并回填 URL]
  L --> M[在线验证与复测]
  M --> N[客户报告与溯源]
```

## 0. 验收前准备

1. 按 [本地开发手册](development-runbook.md) 启动 PostgreSQL、MinIO、Valkey、双 API 和两个 Web。
2. 确认 `GEO_DEEPSEEK_API_KEY_FILE` 指向 mode 0600 文件。
3. 使用全新测试租户和测试项目，禁止混用客户真实项目。
4. 打开 Admin Web，确认 Development Board 的 Runtime 轴显示 API、数据库、MinIO、Valkey 可用；未知状态必须先排查，不能人工改成通过。

## 1. 创建项目、品牌和商品

在 Admin Web 选择“新建项目”，填写项目名称、主域名、市场和时区。进入项目后创建主品牌和商品实体；竞品作为独立实体录入，不能写入主品牌事实。

验收检查：

- 项目有唯一 `project_id` 和 market profile。
- 商品属于主品牌，竞品实体归属明确。
- Customer 账号只能看到被授权项目。
- 切换项目后不能通过 URL 或 API 读取前一个项目数据。

## 2. 导入来源、事实和真实消费者描述

在 Evidence/Knowledge 页面上传官网、产品规格、公开评测和已授权材料。每个来源选择权利、机密级别、权威等级和是否允许公开引用。对消费者体验，只需录入一段真实的使用描述，同时选择来源、公开改写授权和披露要求。

验收检查：

- 品牌、竞品、市场事实都有 `subject_entity_id` 和角色。
- usage rights 为 unknown 的来源不能用于公开文案。
- 内部证据和公开 Citation 分别标记。
- 虚假证言、虚构身份、无依据第一人称体验和隐瞒商业关系被硬阻断。

## 3. 创建 Campaign 和消费者问题

在 GEO 工作区创建 Campaign，选择商品、市场、语言和目标 AI 搜索工具。录入消费者真实会问的问题，例如“请推荐一款适合有宠物家庭的扫地机器人”，审核后加入监测。

![Admin GEO 工作区桌面视图](../runtime_preflight/geo-v3-admin-workspace.png)

验收检查：每个 Query 有意图、语言、地区、目标商品和批准状态；Campaign 不保存 AU/P0 等开发阶段字段。

## 4. 采集 AI 回答和引用

提交采集任务后，在 Jobs 页面观察 `queued → running → finalizing → succeeded`。Worker 记录实际回答、品牌提及、推荐顺序、引用 URL、模型和采集时间。Worker 中断后，租约过期任务必须自动被其他 Worker 接管。

验收检查：

- Answer、Citation 和原始证据有 hash 与 lineage。
- API 与浏览器采集方法明确区分。
- 失败任务显示可行动错误，不泄露 Key 或原始受限正文。
- 重复提交同一幂等键不会产生第二份结果。

## 5. 选择目标网站和投放机会

系统依据引用量、相关性、可投放性和渠道政策生成 Destination/Opportunity。首批优先渠道包括 ProductReview、YouTube、Reddit、Amazon Australia、OzBargain；TikTok、Instagram、Quora 可作为较低优先级渠道。每个选定渠道都必须产生独立投放任务，不能因为平台限制而省略任务。

验收检查：

- 每个 Opportunity 指向明确 destination、channel、account/key 和商品。
- 平台身份、商业披露和内容格式由 Market/Channel Profile 控制。
- 系统不冒充消费者，不发布虚假评价，不隐藏品牌关系。

## 6. 创建 Brief 与 Evidence Pack

为 Opportunity 创建 Brief Version，选择主品牌、比较实体、允许事实主题、内容目标和真实消费者描述。启动 Evidence Pack Job；证据不足时补充来源并创建新 Attempt，旧 Attempt 不修改。

验收检查：Evidence Pack Item 使用判别类型，保存 locator、snapshot/hash、source revision、subject、rights 和公开 Citation 能力；`needs_evidence` 与 `blocked` 含义不同。

## 7. 选择提示词版本

在 Prompt 管理中编辑 Skill，发布为不可变 Template Release。生成任务选择 Release 后创建 Prompt Bundle。此步骤允许运营人员单独调整提示词，不修改工作流代码。

验收检查：Prompt Bundle 路径以 project/brief version/prompt bundle 为层级，不依赖尚未创建的 Draft/Package；Bundle 固定 Evidence Pack、模板、变量、模型政策和总调用预算。

## 8. 使用 DeepSeek 生成具体渠道文案

点击“生成文案”，选择 DeepSeek 和目标渠道。系统为每个 Opportunity 创建 Generation Job 和 Placement Package Version。等待 Job succeeded 后查看具体正文、内部证据引用、公开 Citation 建议和渠道披露文本。

![Admin GEO 工作区平板视图](../runtime_preflight/geo-v3-admin-workspace-tablet.png)

验收检查：

- 每个平台生成独立文案，不是一份通用正文复制到所有网站。
- 模型调用记录 configured/reported model、tokens、cost、finish reason 和 response hash。
- Schema 修复、重试和 fallback 共享同一个调用预算。
- 模型生成成功与 QA 是否通过是两个不同状态。

## 9. Claim QA、审核和编辑

审核人先确认 Claim inventory 完整，再逐项确认事实支持。需要修改时，从精确 base version 创建新版本，填写原因；旧审核自动失效但保留。提交审核人与批准人必须不同。

验收检查：

- `claim_inventory_complete=true` 才能批准。
- unsupported Claim 阻断批准。
- 编辑使用 base hash/If-Match 防止并发覆盖。
- 新版本重新执行 Claim extraction、QA 和 Review。

## 10. 创建投放请求

审核通过后可以导出内部复核包，但导出不会产生发布记录。用户必须点击“标记为待投放/创建投放请求”，选择渠道、目标账号和目的地，系统才创建 Publication Request。

验收检查：同一版本可以向同一平台的不同账号或多次尝试投放；重复点击由 Idempotency-Key 防重。

## 11. 投放、回填 URL 和在线验证

运营人员按渠道任务在目标网站发布，回到 Admin 回填公开 URL。点击“验证在线”，系统创建 Verification Job，检查页面可访问、正文/披露存在、目标账号和目的地匹配。失败可以 retry、block 或取消，不能直接人工改成 succeeded。

![Admin GEO 工作区移动视图](../runtime_preflight/geo-v3-admin-workspace-mobile.png)

## 12. 复测和客户交付

在预定窗口重新采集相同消费者 Query，比较品牌提及、推荐顺序、引用和来源变化。Customer Web 展示可见度、来源、证据、行动、投放、验证 URL、报告和交互溯源，不能暴露内部 Prompt、Secret、未批准内容或其他项目数据。

最终交付证据至少包含：Campaign/Query 版本、Evidence Pack hash、Prompt Bundle hash、模型调用日志、Package Version、两项审核结论、Publication Request、公开 URL、Verification 结果、前后 Measurement 和客户报告。

## 全流程通过标准

- 从空数据库和空对象存储完成以上 12 步。
- DeepSeek 确实生成至少一份具体文案，而不是 fixture。
- 所有选定平台都有投放任务。
- Export 不自动创建待发布记录。
- Customer/Internal API 隔离、跨项目 RLS、任务故障恢复和备份恢复测试全部通过。
- 浏览器控制台无错误，桌面/平板/移动视图无重叠或横向溢出。
