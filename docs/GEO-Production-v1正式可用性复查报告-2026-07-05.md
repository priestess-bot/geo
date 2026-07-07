# GEO Production v1 正式可用性复查报告

生成日期：2026-07-05

对照规划：[GEO-Production-v1完整规划-2026-07-05.md](./GEO-Production-v1完整规划-2026-07-05.md)

对照 checklist：[GEO-Production-v1执行进度-checklist-2026-07-05.md](./GEO-Production-v1执行进度-checklist-2026-07-05.md)

## 1. 复查口径

本次复查采用“正式可用”口径：

1. 只有 Admin Web、Customer Web、Development Board 这三类正式入口可算 Production v1 用户入口。
2. 旧 `/ops` 页面不算正式入口，只能作为迁移参考。
3. 只存在 API、core 代码、脚本、fixture gate、字符串契约测试，不等于功能正式完成。
4. 一个功能要算 Done，必须同时满足：
   - 正式页面可发现；
   - 用户能完成关键操作；
   - 操作后能看到状态、结果、错误反馈；
   - 状态能被 Development Board 或验收报告准确反映；
   - 自动化测试覆盖真实用户路径，而不是只检查源码字符串。

## 2. 总体结论

当前实现存在系统性偏差：

> 大量 checklist `Done` 证明的是后端契约、API、repository、gate 或旧 `/ops` 能力存在，但没有证明正式前端可用。

因此，当前项目不能按 checklist 的 100% 判断为 Production v1 已完成。尤其是报告生命周期、真实采集操作、Google manual backfill、Human Review、Connector Secret、Action Plan、Retest、Content Workbench、Distribution、运维看板等，均存在正式入口缺失或只读摘要问题。

## 3. 关键证据

### 3.1 Admin Web 正式项目详情入口有限

`apps/admin-web/app/projects/[project_id]/page.tsx` 当前只有：

- 基础配置
- 用户入口
- Prompt 配置
- 知识库
- 项目状态
- 全流程测试

项目状态下只有：

- 采集运行
- 评分快照
- 报告
- 报告任务
- 行动计划
- 信源图谱
- 最近生命周期

但这些状态页统一走 `RuntimeSummary`，页面文案明确写着：

```text
运行结果只做摘要展示，不作为配置编辑对象。
```

这意味着采集重试、报告审批发布撤回、行动计划状态、复测创建、证据 drilldown 等核心操作没有正式 Admin Web 闭环。

### 3.2 API 已有，但正式 Admin Web 没有对应动作

API 中已经存在这些能力：

- `/v1/connectors/runtime/secrets`
- `/v1/evidence-runs/runtime/manual-backfill`
- `/v1/evidence-runs/runtime/manual-backfill/import.csv`
- `/v1/human-reviews/runtime`
- `/v1/human-reviews/runtime/queue`
- `/v1/reports/runtime/{report_export_id}/management-events`
- `/v1/report-export-jobs/runtime`
- `/v1/runtime-alerts`
- `/v1/content-engines/runtime`
- `/v1/traceability/runtime`
- `/v1/project-brand-kits/runtime`
- `/v1/project-brand-assets/runtime`
- `/v1/fidelity-checks/runtime`
- `/v1/runtime-saved-views`

但 Admin Web 项目详情 server actions 只覆盖：

- 项目基础信息；
- 启动配置；
- 品牌/竞品实体；
- Prompt 导入和编辑；
- 知识事实导入；
- 邀请、成员、门户 token；
- fixture E2E。

正式 Admin Web 没有对应表单或工作台来操作上述大部分 API。

### 3.3 Customer Web 仍大量直接展示 JSON

`apps/customer-web/app/portal/[module]/page.tsx` 中多个模块仍使用：

```tsx
<pre>{JSON.stringify(..., null, 2)}</pre>
```

涉及：

- 评分解释；
- 信源图谱；
- 证据样本；
- 采集批次；
- traceability bundle；
- 审计摘要；
- 报告任务；
- 行动计划；
- 方法配置。

这不符合 Production v1 客户门户可用性要求。客户页面应展示结构化业务信息、解释、状态和下载入口，而不是原始 JSON。

### 3.4 Development Board 的 100% 不可信

`apps/admin-web/app/development-board/page.tsx` 直接读取 checklist Markdown，然后按 `Done / total` 计算完成率。

它没有检查：

- commit 是否仍是 `待填`；
- 正式页面入口是否存在；
- 用户操作是否可完成；
- Playwright/浏览器交互是否通过；
- 是否只在旧 `/ops` 存在；
- 是否只存在 API 但没有 UI；
- Customer Web 是否仍直接展示 JSON。

所以当前 100% 是 checklist 字段统计，不是 Production v1 可用性结论。

### 3.5 当前自动化测试没有拦住问题

本次运行：

```bash
python3 -m unittest tests.test_admin_customer_web_contracts tests.test_dashboard_web_contracts tests.test_production_v1_gate_contracts
```

结果：

```text
Ran 14 tests in 0.324s
OK
```

但这些测试主要是源码字符串契约检查，例如检查某些端点、组件名、文案是否存在。它们没有验证正式页面是否可以完成报告发布、Google backfill、Human Review、Content Workbench、Distribution URL 回填等真实流程。

## 4. 问题矩阵

| 编号 | 功能 | checklist 当前状态 | 实际可用状态 | 缺失类型 | 严重级别 | 证据 | 整改方向 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P0-01 | Development Board / checklist 完成率 | 多项 Done，Final Gate Done | 100% 仅来自 Markdown 状态字段 | 状态误报 | P0 | `development-board/page.tsx` 只解析 checklist | 增加正式入口、交互测试、commit、UI gate 维度；缺失时不得显示完成 |
| P0-02 | Admin Web 项目状态 | Collection/Score/Report/Action 等 Done | 只读摘要，不可操作 | 只读摘要 | P0 | `RuntimeSummary` 文案“不作为配置编辑对象” | 拆成可操作工作台：采集、评分、报告、行动、复测、证据 |
| P0-03 | Report 生成、审批、发布、撤回 | W6-I01a-f Done | Admin Web 无正式操作入口 | 无正式入口 | P0 | API 存在，Admin actions 未接入 | 增加报告中心：生成、预览、审批、发布、撤回、下载、审计 |
| P0-04 | Report Export Job | Done | 只能摘要查看 job，不能创建/重试/更新状态 | 只读摘要 | P0 | `/v1/report-export-jobs/runtime` 只在页面 loadPage | 增加任务创建、状态更新、失败重试、artifact 状态 |
| P0-05 | Connector Secret 管理 | W3-I00 Done | 启动配置只写 env var/备注，不接 secret API | API 未接 UI | P0 | `/v1/connectors/runtime/secrets` 无 Admin action | 增加 secret 创建、轮换、masked list、权限和 redaction UI |
| P0-06 | Google manual backfill | W3-I04 Done | 无正式 Admin Web 补录入口 | 无正式入口 | P0 | API 存在但 Admin Web 无 action | 增加 Google manual 单条/CSV 补录、证据 URL、状态和错误反馈 |
| P0-07 | Human Review / manual correction | W5-I01 Done | 无复核队列、无人工修正入口 | 无正式入口 | P0 | `/v1/human-reviews/runtime` 未接 Admin Web | 增加解析结果复核队列、修正、保存、审计 |
| P0-08 | Evidence / Traceability drilldown | W4-I01c-d Done | Admin 只摘要；Customer 多处 JSON | 只读摘要 / JSON 暴露 | P0 | Customer portal 多处 `<pre>JSON.stringify` | 增加证据详情、引用、asset proxy 下载、报告数字追溯链路 |
| P0-09 | Action Plan | W7-I01 Done | Admin 只摘要；Customer 展示 JSON；不可改 owner/status/customer_visible | 只读摘要 | P0 | `status_tab=actions` 使用 `RuntimeSummary` | 增加行动计划工作台：负责人、状态、客户可见、关联证据 |
| P0-10 | Retest | W7-I02 Done | 项目页没有创建复测和 before/after delta 操作入口 | 无正式入口 | P0 | 没有 retest tab/action | 增加复测创建、平台选择、结果比较、报告段落 |
| P0-11 | Customer Web 登录/邀请/项目列表 | W2/W6 Done | 仍以 query `portal_token` 打开单项目；无项目列表 | 产品路径不完整 | P0 | Customer home token form | 接 invitation/session 登录；客户登录后看授权项目列表；避免长期 URL token 作为主路径 |
| P0-12 | Customer Web 报告解释页 | W6-I01e Done | 报告下载有入口，但解释/证据/任务大量 JSON | 客户体验不可投产 | P0 | `portal/[module]/page.tsx` 多处 `<pre>` | 改为客户可读的结构化卡片、表格、状态和方法说明 |
| P0-13 | Development Board / Ops 可观测入口 | W9-I01 Done | 独立 Dashboard Web 已退役，文档/审计/下一步/门禁已合并到 Admin Web `/development-board`；只读运维卡片仍需继续接 live API/DB/worker/connector/cost | 部分整改 | P0 | Development Board 读取 checklist、当前文档和 smoke artifact；dashboard-web 仅保留退役提示页 | 继续增加只读运维看板：health、ready、metrics、alerts、backup、queue、cost |
| P0-14 | 正式全流程测试入口 | C03/C05 Done | Admin Web E2E 仍是 fixture dev tool；正式流程靠命令，不是产品操作路径 | 流程不可见 | P0 | `FixtureE2EForm` + 生产环境隐藏 | 增加 Production workflow checklist 和真实运行状态页，fixture 只保留 dev |
| P1-01 | Knowledge Base | W8-I01 Done | 当前有结构化 CSV/文本导入和检索，但不是完整知识库管理 | 功能偏薄 | P1 | Admin `KnowledgePanel` 已有薄入口 | 增加事实列表、编辑、归档、来源、审核、批量导入历史 |
| P1-02 | Content Workbench | W8-I02 Done | 无正式 Admin Web 内容工作台 | 无正式入口 | P1 | `/v1/content-engines/runtime` 未接 Admin Web | 增加内容草稿列表、详情、审核、修改、客户/内部可见状态 |
| P1-03 | Distribution task 回填 | W8-I03 Done | 无正式 URL/proof 回填入口 | 无正式入口 | P1 | API/core 存在，正式页面无入口 | 增加分发任务列表、URL/proof 回填、状态和复测关联 |
| P1-04 | Brand kit / logo / assets | API 已存在 | 品牌页只管实体字段，不管 logo/assets/scan/activate | API 未接 UI | P1 | brand kit API 未接 Admin Web | 增加品牌资产管理、logo 上传、扫描状态、启用资产 |
| P1-05 | Fidelity checks | API 已存在 | 无正式页面查看或创建 | 无正式入口 | P1 | `/v1/fidelity-checks/runtime` 仅 API/旧 ops | 增加质量检查列表、创建、趋势、导出 |
| P1-06 | Saved views | API 已存在 | 无正式页面保存筛选视图 | 无正式入口 | P1 | `/v1/runtime-saved-views` 仅 API/旧 ops | 在项目工作台加入保存视图、恢复视图 |
| P1-07 | Entity alias assignment | API/旧 ops 已存在 | 不在正式 Admin Web | 旧入口依赖 | P1 | `/v1/entity-aliases/runtime...` 在旧 `/ops` | 迁移为正式别名审核/分配工作台或标记后续升级 |
| P0-15 | 测试体系 | 多个 gate Done | 缺少浏览器级正式用户路径测试 | 测试缺失 | P0 | unittest 只做字符串契约 | 增加 Playwright/HTTP flow 测试和 UI/API 映射 gate |

## 5. 当前状态建议调整

建议不要继续把以下项目作为“正式完成”展示：

1. `C03 Production v1 E2E 从空环境跑通`
2. `C04 Enablement v1 E2E 跑通`
3. `C05 Final Gate 全部通过`
4. `W6-I01d Approval/publish/revoke lifecycle`
5. `W7-I01 Action Plan 最小闭环`
6. `W7-I02 Retest 最小闭环`
7. `W8-I02 Content Workbench 薄闭环`
8. `W8-I03 Distribution task 回填`
9. `W9-I01 Observability 最小生产门禁`

更准确的状态应是：

```text
Backend/API/Gate Done
Formal UI Pending
Runtime UX Not Verified
```

Development Board 应该把这种状态显示为黄色或红色，而不是 Done。

## 6. 整改 Backlog

### R0：先修完成口径和看板真实性

1. 修改 checklist 状态模型：
   - `Backend Done`
   - `API Done`
   - `Formal UI Pending`
   - `Runtime Verified`
   - `Production Done`
2. Development Board 不再只按 Done 计算完成率。
3. 每个工作项增加：
   - 正式入口 URL；
   - 关键用户动作；
   - Playwright/交互测试；
   - commit hash；
   - 旧 `/ops` 是否仍依赖。
4. 新增 gate：
   - `make official-ui-contract-smoke`
   - `make development-board-truth-smoke`

### R1：修 P0 正式产品闭环

1. Admin Web 增加 Connector Secret 工作台。
2. Admin Web 增加真实采集/Google manual backfill 工作台。
3. Admin Web 增加 Human Review 工作台。
4. Admin Web 增加 Evidence / Traceability drilldown。
5. Admin Web 增加 Report Center：
   - 生成；
   - 预览；
   - 审批；
   - 发布；
   - 撤回；
   - artifact 下载；
   - 管理事件审计。
6. Admin Web 增加 Action Plan / Retest 工作台。
7. Customer Web 去除原始 JSON 展示，改为客户可读页面。
8. Customer Web 改成 invitation/session 登录和授权项目列表优先。
9. Dashboard/Development Board 增加 live ops 状态：
   - API health；
   - DB health；
   - worker/queue；
   - connector health；
   - report jobs；
   - alerts；
   - backup；
   - provider cost。

### R2：修 P1 Enablement 正式入口

1. Knowledge Base 从“导入+检索”扩展为管理工作台：
   - 列表；
   - 编辑；
   - 归档；
   - 审核；
   - 来源；
   - 导入历史。
2. Content Workbench 正式接入：
   - 内容草稿；
   - 证据来源；
   - 审核；
   - 修改；
   - 状态。
3. Distribution task 正式接入：
   - 任务列表；
   - URL/proof 回填；
   - 状态变更；
   - retest linkage。

### R3：补测试和反验收

新增测试必须覆盖真实入口，而不是只检查源码字符串：

1. Admin Playwright E2E：
   - 创建 connector secret；
   - 导入 Google manual backfill；
   - 完成人工复核；
   - 生成报告；
   - 审批发布；
   - 撤回报告；
   - 创建行动计划状态更新；
   - 创建 retest 并查看 delta。
2. Customer Playwright E2E：
   - invitation 登录；
   - 查看授权项目；
   - 查看评分；
   - 下载 PDF/CSV；
   - 查看证据摘要；
   - 查看行动计划；
   - revoked report 访问失败。
3. Development Board truth tests：
   - 任一 `Formal UI Pending` 不得计入 Production Done；
   - commit `待填` 不得计入最终完成；
   - 旧 `/ops` 入口不得计入正式入口；
   - Customer Web `<pre>{JSON.stringify(...)}</pre>` 不得出现在生产客户模块。

## 7. 验收标准

整改完成后，以下条件必须同时成立：

1. Development Board 不再显示虚假的 100%。
2. 每个 Production v1 P0 工作项都能从正式页面进入。
3. 每个 P0 工作项至少有一个真实用户动作可执行。
4. Customer Web 不再用 JSON 作为主要信息展示形式。
5. 旧 `/ops` 不再作为任何 P0/P1 功能的唯一入口。
6. Final Gate 包含正式 UI 交互测试。
7. checklist 的 Done 必须对应 `Production Done`，而不是 backend/API done。

## 8. 本次复查后判断

当前项目已经有不少后端、API、repository、gate 基础，但离“正式客户可用”仍有明显缺口。

最主要的问题不是某一个页面漏做，而是完成定义错误：

> 目前 checklist 把 backend/API/gate 完成当成了产品完成。

后续必须先修完成口径和正式入口缺口，否则继续堆 API 或测试会继续出现“文档写 Done，但用户找不到页面”的问题。
