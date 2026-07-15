# GEO v3 全流程运行手册

> 状态：交付验收手册（实现完成后按本手册运行）
>
> 适用范围：以 AI 搜索和回答中可复核的品牌、产品、引用与推荐可见度为目标的人工渠道投放工作流。

## 1. 目的与边界

本系统用于把经过审核的品牌信息、产品事实和公开资料，组织为适合具体网站或账号的内容包，并记录人工投放、公开 URL 验证和后续 AI/搜索观察。

它不承诺 ChatGPT、Google 或任何平台一定推荐某品牌；不自动登录第三方平台、不自动发帖、不购买广告、不管理合同或付款；也不生成伪装消费者、虚假评价、虚构使用体验或隐蔽商业关系内容。

完整链路：

```text
项目与商品
-> Campaign
-> 查询建议与人工批准
-> ChatGPT Search / Google 基线观察
-> 渠道目的地审核与投放机会
-> Brief、证据包、可版本化 Prompt
-> 文案包生成与双人审核
-> 导出并人工投放
-> 回填公开 URL 并验证
-> T+28 / T+56 / T+84 同口径复测
-> 管理台和客户门户报告
```

管理员工作区验收截图（真实运行中的样例项目）：

![GEO 投放工作区](runtime_preflight/geo-v3-admin-workspace.png)

## 2. 角色与职责

| 角色 | 职责 | 不能做的事 |
| --- | --- | --- |
| 项目 Owner/Admin | 建立项目、商品、Campaign、渠道授权和成员 | 不能自行批准自己提交的文案包 |
| Analyst | 导入观察、维护查询建议、建立机会、记录测量 | 不能绕过渠道资格和证据门禁 |
| Content Operator | 配置 Prompt、创建 Brief、生成和导出文案包、回填人工提交信息 | 不能自动发布或批准自己提交的文案包 |
| Reviewer | 审核事实完整性、Claim 支撑、披露和渠道合规；批准或退回文案包 | 不能批准自己提交审核的包 |
| 客户 Viewer | 查看已验证投放、测量趋势和已发布报告 | 不能读取内部 Prompt、原始证据或未审核内容 |

## 3. 启动与运行前检查

### 3.1 启动服务

从仓库根目录运行：

```bash
make docker-up-auto-ports
```

记录命令输出的 Admin Web、Customer Web 与 API 地址。正式上线前必须另做一次新数据库卷安装演练；日常回归或明确指定的现有环境验收，可以保留当前数据，但必须记录起始 commit、脏工作区状态和执行前后对象数量。

### 3.2 必须通过的健康检查

1. API 健康检查正常，Admin Web 和 Customer Web 可打开。
2. 数据库迁移包含 GEO v3 运行时表及项目 RLS 策略。
3. 对象存储可用，能保存证据快照、Prompt Bundle 与导出工件。
4. 生成、验证和测量命令可用；现阶段文案生成由 API 同步调用模型，验证和测量由人工发起，不能把它表述为已经部署的 GEO 专用后台 Worker。
5. 模型网关已配置，或界面明确显示生成不可用且不允许创建伪成功结果。

### 3.3 运行前资料清单

每个产品 Campaign 至少准备：

- 品牌名称、主产品名称、产品 URL、目标市场和外部语言；
- 真实且可公开使用的产品资料、规格、FAQ、保修/配送/价格规则；
- 每项资料的原始 URL 或文件、版本/hash、使用授权和公开引用限制；
- 已授权的自有站、商城店铺、官方社媒或代表账号；
- 渠道政策、允许的披露方式和禁止事项；
- 参与审核和人工投放的人员。

只提供一段真实消费者使用描述时，作为 `brand_authored` 或 `verified_experience` 的原始输入保存；系统只可在原意和披露边界内改写，不将其伪装为独立第三方评价。

## 4. 建立项目、商品与 Campaign

### 4.1 创建项目

1. 在 Admin Web 新建客户项目，填写品牌、市场、品类和项目 Owner。
2. 邀请 Analyst、Content Operator、Reviewer 和客户 Viewer。
3. 用两个不同账号确认提交人不能审批自己的文案包。

### 4.2 创建商品

为每个要影响 AI 推荐的商品建立独立商品记录，填写：名称、品牌、产品页、类别、市场、可用规格、公开资料和状态。

不要把多个不同产品混在同一 Campaign。以 ADVINSYS 为例，TerraMow V600、TerraMow V1000 与 Seauto SAT30 必须是三个 Campaign。

### 4.3 创建 Campaign

1. 选择一个主商品。
2. 固定市场（例如 `AU`）和外部语言（例如 `en-AU`）。
3. 设置目标为 `recommendation_influence`。
4. 记录业务目标、禁止 Claim、竞争品和投放边界。
5. 将 Campaign 设为 `active` 前，确认至少有一项可用事实来源和一个可审核渠道。

## 5. 查询、观察与基线

### 5.1 查询建议和批准

系统可基于商品类别、竞品、已有回答、来源缺口和搜索词提出查询建议。运营人员必须逐条：

1. 阅读查询的消费者意图和适用商品；
2. 标记为批准、拒绝或停用；
3. 为已批准查询冻结市场、语言、设备和样本数；
4. 避免把品牌名强塞进通用推荐查询，保留真实消费者问法。

### 5.2 导入基线观察

观察平台固定为 ChatGPT Search 与 Google。每个批准查询、每个平台每次采集 3 个样本。

在 Admin Web 的“导入基线/复测观察”表单选择已批准查询，填写原始回答/搜索结果、每行一个引用 URL、截图或导出工件 URL、阶段、样本编号和可见模型。不要只录入汇总分数。市场、语言和设备继承已冻结的查询条件。

发布前至少连续 28 天按周导入观察。基线一旦冻结，只能新增更正记录，不能覆盖原始样本。

## 6. 全部渠道的投放任务

每个渠道都必须建立具体 `Destination` 与投放任务；“建立任务”不等于允许自动发布。

| 渠道 | 典型任务 | 必须确认 |
| --- | --- | --- |
| 自有官网 | 产品页、FAQ、比较页 | 域名/编辑权限、品牌披露、链接目标 |
| Amazon | 商品详情、A+ 内容、卖家资料 | 卖家授权、商品归属、平台规则 |
| YouTube | 视频脚本、说明、创作者 Brief | 官方账号或创作者同意、商业披露 |
| TikTok / Instagram | 短视频脚本、caption、素材 Brief | 账号授权、广告/合作披露 |
| ProductReview | 商家资料、合规官方回复任务 | 商家身份、禁止伪造消费者评价 |
| Reddit | 明确身份的官方参与任务 | Subreddit 规则、官方身份、关系披露 |
| OzBargain | 优惠提交任务 | 商家资格、优惠真实性、关系披露 |
| Quora | 明确关系的专业回答任务 | 主题相关性、事实来源、关系披露 |

每个 Destination 均需保存具体 URL/账号、任务类型、权限/资格、渠道政策快照、政策复核人、复核时间和披露要求。未审核、受限或禁止的 Destination 只能观察，不能生成可提交包。

## 7. 证据、Prompt 与文案包

### 7.1 建立 Brief 和 Evidence Pack

对一个 Campaign、查询和 Destination 创建 Brief。Evidence Pack 只选用已批准事实、Chunk 或公开资料，并保存来源版本和 hash。

不得把以下内容作为可覆盖风险：伪造评价、虚假身份、未经支持的第一人称体验、隐瞒商业关系、未经授权的个人信息或受限数据。

### 7.2 管理 Prompt

Prompt/Skill 在独立管理界面中维护：

1. 新建草稿版本，包含 System Template、User Template、变量 schema、输出 schema 和测试集；
2. 用固定 Evidence Pack 进行测试；
3. 审核后发布该版本；
4. 需要回退时选择此前已发布版本；
5. 每个文案包永久记录实际使用的 Prompt/Skill/Output Schema 版本及渲染 hash。

业务流程只能使用 Task Key，例如 `placement.reddit.disclosed_official_post` 或 `placement.amazon.listing`。修改文字提示词不得绕过证据、披露、账号授权或人工审核门禁。

### 7.3 生成与人工编辑

生成器使用 Campaign、Brief、Evidence Pack、Destination Policy 和 Prompt Bundle 创建不可变内容包。内容包至少包含标题、正文、CTA、链接、公开引用、披露文本、提交说明和 Claim 清单。

如需编辑，基于精确内容版本创建新包或新版本，填写修改原因。旧包保留历史，但此前审批失效；新版本必须重新执行 Claim 抽取、完整性确认和审核。

### 7.4 DeepSeek 实际生成验收

当启用模型生成时，API 只从只读 secret 文件加载 DeepSeek Key，不在请求、日志、响应或审计记录中返回 Key。每个成功结果必须记录 `generation_model=deepseek-chat`、`model_response_hash`、Prompt Version、Evidence Snapshot 与内容 hash。

可重复执行的实时测试位于 `tests/test_geo_deepseek_live_generation.py`。它是显式 opt-in，避免默认测试套件消耗模型费用：

```bash
GEO_RUN_LIVE_DEEPSEEK_TEST=1 \
GEO_LIVE_PROJECT_ID=<project-id> \
GEO_LIVE_OPPORTUNITY_ID=<opportunity-id> \
GEO_LIVE_PROMPT_VERSION_ID=<prompt-version-id> \
GEO_LIVE_EVIDENCE_URL=<approved-source-url> \
GEO_LIVE_EVIDENCE_TEXT='<approved-evidence-text>' \
python3 -m unittest tests/test_geo_deepseek_live_generation.py
```

验收时必须检查返回包的模型名和 64 位响应 hash，且继续完成双人审核；仅有本地模板或手填正文不可以替代该测试。

### 7.5 九渠道生成与质控复查

本轮只验收到 `approved`，不创建 Submission。执行前先确认目标项目已有独立 `content_operator` 和 `reviewer`，再运行：

```bash
GEO_QC_RUN_ID=<run-id> python3 scripts/run_geo_v3_full_qc.py
```

执行器将检查官网、Amazon AU、YouTube、TikTok、Instagram、ProductReview、Reddit、OzBargain 和 Quora。每个渠道都必须形成带 `task_key` 的持久任务记录；具备真实来源、账号/目的地和上下文的渠道调用 DeepSeek，缺少优惠、评价上下文或账号授权的渠道保留为 `candidate` 并输出 `needs_evidence`，不能创建可生成 Opportunity，也不能用测试事实代替。

每个生成包必须保存 Prompt Bundle hash、模型响应 hash、Evidence snapshot 和逐 Claim 映射。质控低于 85 分、存在 unsupported Claim、身份披露不足或渠道格式不合格时，基于原 content hash 创建新版本，旧版本变为 `superseded`，新版本重新审核。

本次可复查样例位于 `docs/runtime_preflight/geo-v3-full-review/20260714-full-qc-v1/`：六个渠道形成已批准文案；ProductReview、OzBargain 和 Quora 因缺少真实前置条件被阻断；执行前后 Submission 数量均为 1。目录内的渠道矩阵、Prompt Bundle 清单、内容 QC 报告、负向测试和最终判定共同构成本轮验收证据，不能只查看一篇生成文案就宣称全流程通过。

## 8. 审核、导出与人工投放

### 8.1 审核

Reviewer 必须独立完成：

1. Claim inventory 完整性确认；
2. 每条事实 Claim 与 Evidence 支撑确认；
3. 品牌、竞品、市场主体归属确认；
4. 公开引用、授权、披露、CTA、链接和渠道规则确认；
5. 批准、退回修改或阻断。

批准还必须填写 0-100 质控分数和质控报告。低于 85 分不得批准。Reviewer 页面应显示正文、Evidence、Prompt Bundle hash、Content hash 和每条 Claim 的 support 状态。

`submitted_for_review_by` 与 `approved_by` 必须不同。未批准包不得进入提交步骤。

### 8.2 导出与提交

在 Placement Workspace 的“文案包预览与导出”区域先核对正文和披露，再点击“下载 Markdown 文案包”。导出内容包只表示下载或交付，不能自动创建 Submission、发布记录或 Campaign KPI。

人工操作人员按渠道政策登录相应平台完成操作，并在系统中创建 Submission，记录提交时间、操作者、目的地、提交证据和可选外部平台编号。系统不得保存第三方账号密码，也不得自动点击发布。

## 9. URL 回填、公开验证与复测

### 9.1 回填和验证

发布后回填真实公开 URL。验证任务检查：页面可访问、目标内容存在、关键文本或 hash 匹配、必要披露存在、链接正确、页面未被删除或替换。

验证失败、不可访问、内容不匹配或披露缺失时，Submission 保持失败/待修复，不能计入已验证投放覆盖，也不创建有效效果归因。

### 9.2 测量窗口

仅在 URL 验证成功后创建 T+28、T+56、T+84 测量待办。每次复测复用已冻结的查询、地区、语言、设备、平台和每查询样本数。

若模型、搜索界面、价格、库存、季节、竞品或产品版本发生明显变化，标记 `confounded`，报告只能描述观察到的变化，不能宣称投放造成了变化。

## 10. Dashboard、客户门户与报告

Admin Web 必须提供四个工作区：

1. Campaign：商品、查询、基线和指标；
2. Observations：原始样本、引用和导入工件；
3. Destinations & Opportunities：渠道政策、资格、投放任务和阻断原因；
4. Placement Workspace：Brief、Evidence、Prompt、文案包、审核、提交、URL 验证与测量。

Customer Web 只读展示已验证 URL、投放状态、推荐/提及/引用趋势、测量窗口和已批准报告，不显示未审核文案、内部 Prompt 或原始受限证据。

## 11. 异常处理

| 情况 | 处理 |
| --- | --- |
| 模型 Key 未配置或调用失败 | 不生成成功内容；保留失败原因，可在配置完成后重试 |
| 事实不足或来源授权未知 | 阻断生成，进入补充资料队列 |
| 渠道规则变化或账号失权 | 暂停 Destination，已有任务重新审核 |
| 文案被退回 | 创建修订版本，旧审批失效，重新审核 |
| 公开 URL 失效/内容改写 | 验证状态变为失效，停止后续有效覆盖计算 |
| 模型调用中断 | 请求不创建成功文案包；记录失败原因后由操作者重新发起生成 |
| 数据或权限异常 | 立即停用相关 Destination/成员会话，保留审计记录并通知 Owner |

## 12. 最终验收记录

交付时逐项附上证据：

1. 新环境启动命令、服务 URL、健康检查输出；
2. 一个真实 Campaign 的完整对象 ID 链路；
3. 三个样本的 ChatGPT Search 与 Google 基线导入证据；
4. 每个首批渠道至少一个合规投放任务；
5. 一个通过双人审核的内容包及其 Prompt/Evidence/Claim lineage；
6. 一次实际 DeepSeek 生成结果及其 `generation_model`、响应 hash 和双人审核记录；
7. 一次人工提交和成功/失败 URL 验证记录；
8. T+28/T+56/T+84 测量任务及冻结条件；
9. 客户门户只读展示截图；
10. 跨项目访问、同人审核、无证据生成、导出即发布、验证失败计 KPI 等负向测试结果。

未能提供以上任一项的可复现证据时，GEO v3 不得标记为“完全可用”。
