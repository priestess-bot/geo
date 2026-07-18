# ADVINSYS GEO 项目部署与运维全流程操作手册

版本：1.0  
适用项目：`ADVINSYS Australia`  
真实项目 ID：`983fa88d-097a-4252-9ab3-fc4371799c55`  
适用角色：Platform Operator、Project Owner、Content Operator、Independent Reviewer、Customer  
最后复核：2026-07-18

本文档是独立操作手册。操作员只按本文件即可完成环境部署、ADVINSYS 项目初始化、知识录入与清洗、内容生产、人工投放、监测、客户交付和日常运维。

## 1. 完成口径与数据边界

完整验收由两条互不混用的数据链组成：

| 数据链 | 用途 | 允许的数据 | 禁止事项 |
| --- | --- | --- | --- |
| 真实项目 | 客户实际运营 | 真实来源、真实模型调用、真实账号状态、真实 URL、真实观察 | 不得写入仿真 URL、提前生成的 T+28 指标或虚构已发布状态 |
| 独立 Staging 仿真 | 验证系统所有状态和客户页面 | 显著标记的受控 URL、观察、T+28/T+56/T+84、报告 | 不得复制回真实项目，不得称为真实投放结果 |

最终必须保存两份回执：

1. `actual-provision-receipt.json`：真实项目结构和当前真实状态。
2. `simulation-acceptance-result.json`：独立 Staging 的完整状态链，`controlled_simulation=true`。

第三方账号、外网或等待窗口不可用时，真实任务保持 `blocked`、`awaiting submission` 或 `scheduled`；完整功能由 Staging 仿真验证。DeepSeek 正式生成不使用仿真替代，缺少 Key 时应记录为阻断项。

## 2. ADVINSYS 项目范围

结构化输入文件：`docs/target_company/advinsys-geo-project.json`。文本原件：`docs/target_company/目标公司相关内容.txt`。

### 2.1 产品和市场

| 对象 | 固定值 |
| --- | --- |
| 品牌 | ADVINSYS |
| 市场 | AU / en-AU / Australia/Sydney |
| 产品 1 | ADVINSYS TerraMow V600 |
| 产品 2 | ADVINSYS TerraMow V1000 |
| 产品 3 | ADVINSYS Seauto SAT30 |

### 2.2 渠道

九个标准渠道全部必须产生投放任务：Owned Site、ProductReview、YouTube、Reddit、Amazon AU、OzBargain、TikTok、Instagram、Quora。Facebook 作为可选 `other` 渠道，不进入九渠道 KPI 分母。

当前缺少 ProductReview、Reddit、OzBargain、Quora 的明确账号或目标页面，因此在真实项目中保持 `restricted/blocked`。Amazon 在卖家授权确认前也保持 `restricted`。已有公开地址不等于账号授权；执行当天必须复核。

## 3. 操作前记录与安全检查

每次部署或正式运行先创建记录目录：

```bash
cd /home/ymm/ym/gz/20260608-geo
export RUN_ID="advinsys-$(date +%Y%m%d-%H%M%S)"
mkdir -p "artifacts/runs/$RUN_ID"
git rev-parse HEAD | tee "artifacts/runs/$RUN_ID/git-commit.txt"
docker version | tee "artifacts/runs/$RUN_ID/docker-version.txt"
```

不得把以下内容写入 Git、截图、故障单或客户报告：DeepSeek Key、OIDC Client Secret、数据库密码、MinIO 密钥、Session Cookie、邀请 Token、受限 Evidence 原文。

DeepSeek Key 文件必须是绝对路径且权限为 `0400` 或 `0600`：

```bash
chmod 600 /absolute/path/to/deepseek_api_key.txt
stat -c '%a %n' /absolute/path/to/deepseek_api_key.txt
```

![运行记录样例](images/01-run-record.png)

## 4. 启动开发验收环境

本地开发环境用于真实项目操作演示，不等于生产环境。

```bash
export GEO_DEEPSEEK_API_KEY_FILE="$PWD/deepseek_api_key.txt"
make dev-up
docker compose -f infra/docker-compose.yml --profile workers ps
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
curl -fsS -o /dev/null http://localhost:3001/projects
curl -fsS -o /dev/null http://localhost:3000
```

正常结果：PostgreSQL、MinIO、Valkey 为 `healthy`；两个 API、两个 Web、Worker 和 Outbox Relay 为 `Up`；健康接口返回 2xx。

![服务健康样例](images/02-stack-health.png)

启动失败：

```bash
docker compose -f infra/docker-compose.yml --profile workers logs --tail=300 \
  postgres minio valkey migrate internal-api customer-api task-worker outbox-relay admin-web customer-web
docker compose -f infra/docker-compose.yml --profile workers up -d --build --wait
```

不要直接删除 Volume。只有确认全部是可删除测试数据时，才设置 `CONFIRM_DELETE_TEST_DATA=1` 并执行开发重置。

## 5. 启动独立 Staging 仿真环境

Staging 必须使用不同 Compose Project、端口和 Volume。

```bash
cp infra/staging.env.example "artifacts/runs/$RUN_ID/staging.env"
chmod 600 "artifacts/runs/$RUN_ID/staging.env"
sed -i "s|/absolute/path/to/deepseek_api_key.txt|$PWD/deepseek_api_key.txt|" \
  "artifacts/runs/$RUN_ID/staging.env"
docker compose -p geo-advinsys-staging \
  --env-file "artifacts/runs/$RUN_ID/staging.env" \
  -f infra/docker-compose.yml --profile workers up -d --build --wait
```

默认 Staging 入口：Admin `http://localhost:13001`、Customer `http://localhost:13000`、Internal API `http://localhost:18000`、PostgreSQL `localhost:55433`、MinIO Console `http://localhost:19001`。

确认 Staging 与开发环境的 Compose Project 和 Volume 名不同：

```bash
docker compose ls
docker volume ls | grep -E 'geo-development|geo-advinsys-staging'
```

## 6. 生产部署

生产使用 `infra/compose.prod.yml` 和本地不入库的 `infra/production.env`。上线前必须填写：公开 Admin/Customer 域名、TLS/反向代理、OIDC Issuer/Audience/Claim、Owner 身份、数据库三类角色密码、MinIO Root/API/Worker 凭据、Session Secret、DeepSeek Key 路径、备份目录和保留期。

```bash
cp infra/production.env.example infra/production.env
chmod 600 infra/production.env
docker compose --env-file infra/production.env -f infra/compose.prod.yml config -q
make production-up PROD_ENV=infra/production.env
make production-provision-owner PROD_ENV=infra/production.env
```

生产验收必须通过 TLS 域名，不能把开发身份头或 MinIO Console 暴露到公网。首次业务写入前执行第 25 章备份恢复演练。

## 7. 初始化并核验 ADVINSYS 真实项目

先做不写数据的清单检查：

```bash
uv run python scripts/provision_advinsys_project.py \
  --manifest docs/target_company/advinsys-geo-project.json \
  --mode actual --dry-run \
  --receipt "artifacts/runs/$RUN_ID/actual-dry-run.json"
```

预期为 3 产品、9 标准渠道、3 Campaign、27 Opportunity、6 Query、6 Knowledge Source、4 初始 Evidence。

执行幂等初始化：

```bash
uv run python scripts/provision_advinsys_project.py \
  --api-url http://localhost:8000 --mode actual --apply \
  --manifest docs/target_company/advinsys-geo-project.json \
  --receipt "artifacts/runs/$RUN_ID/actual-provision-receipt.json"
```

再执行两次只读核验，两次都必须 `ok=true` 且数量不增长：

```bash
uv run python scripts/provision_advinsys_project.py --verify-only \
  --receipt "artifacts/runs/$RUN_ID/actual-verify-1.json"
uv run python scripts/provision_advinsys_project.py --verify-only \
  --receipt "artifacts/runs/$RUN_ID/actual-verify-2.json"
```

打开 `http://localhost:3001/projects`，搜索 `ADVINSYS`，按项目名称进入，不凭长 ID 识别客户。

![项目列表](images/03-admin-project-list-desktop.png)

## 8. 项目基础配置

入口：`项目工作台 → 基础配置`。

1. 项目名称确认 `ADVINSYS Australia`，状态为“运行中”。
2. 实体列表确认一个主品牌和三个产品；规范 URL 指向稳定官方页。
3. 市场确认 `AU`、`en-AU`、`Australia/Sydney`。
4. 高级属性没有既定 Schema 时保持原值，不临时手写 JSON。
5. 每次保存后刷新，确认值未回退。

![基础配置](images/22-project-basic-current.png)

## 9. 成员、角色和客户邀请

入口：`项目工作台 → 用户入口`。

至少准备两个不同内部身份：Content Operator 负责提交审核；Reviewer/Admin 负责独立审核。`submitted_for_review_by` 不得等于 approver。

添加内部成员：填写 OIDC Issuer、Subject、邮箱、显示名和角色；保存后用该身份重新登录验证项目权限。客户邀请选择 `customer` Surface，设置合理过期时间，邀请 ID 与 Token 通过受控渠道分别交付。

必须测试：错误 Admin 入口不消耗 Customer 邀请、过期邀请失败、撤销后失败、成功兑换后不能重复使用、多项目客户仍可切换已有项目。

![成员与客户入口](images/04-catalog-members-desktop.png)

## 10. 知识来源录入

入口：`项目工作台 → 知识库 → 导入`。

支持三种直接输入和一种降级方式：

| 方式 | 必填 | 用途 |
| --- | --- | --- |
| URL | 来源标题、公开 URL | 官网、产品页、公开帮助页 |
| 文件 | 标题、文件 | PDF、DOCX、TXT、Markdown、HTML 导出 |
| 文本 | 标题、原文 | 授权声明、渠道登记、短事实 |
| 授权账号导出 | 先从平台导出，再按文件导入 | 登录墙、反爬或 JS 页面 |

ADVINSYS 应至少包含官网、V600、V1000、SAT30、Amazon Store 和授权渠道登记六个来源。社交账号首页不能自动证明具体产品 Claim；需要公开内容 URL 或带来源时间的授权导出。

单个来源上限 5 MB。导入前记录来源主体、产品、授权、保密级别、可否公开引用和修订日期；当前 UI 未提供的治理字段在正式 Evidence 阶段补齐。

![知识导入](images/05-knowledge-import-desktop.png)

## 11. 六阶段清洗与重处理

入口：`知识库 → 处理任务`。固定阶段为：接收来源、解析正文、清洗去重、语义分块、事实候选、质量检查。

1. 每个来源等待 Run 进入 `succeeded`。
2. 展开阶段，确认六项都有开始、结束和输出摘要。
3. `failed` 时先看 error detail，再修复来源或网络后点击“重处理”。
4. 重处理产生新 Run，旧 Run 保留审计，不改旧状态。
5. Worker 重启后，过期租约任务应被重新领取；若仍 `running`，检查 Worker、Outbox 和租约时间。

![知识处理任务](images/05-knowledge-processing-desktop.png)

## 12. Chunk、检索和质量治理

### 12.1 Chunk 可视化

入口：`知识库 → Chunk 可视化`。逐个检查来源、序号、正文、hash 和质量标记。导航、Cookie、页脚、混合产品或错误主张不能用于生成时点击“禁用”；禁用只影响后续选择，不删除审计记录。

![Chunk 可视化](images/05-knowledge-chunks-desktop.png)

### 12.2 检索

入口：`知识库 → 检索`。分别搜索 `V600`、`600 square metres`、`V1000`、`SAT30`、`removable battery`。结果必须来自正确产品，不得把竞品或其他型号描述混入。

![知识检索](images/05-knowledge-search-desktop.png)

### 12.3 看板和质检

入口：`知识库 → 知识库看板/质检`。失败 Run 和开放 Finding 在内容生产前必须有处置。只有确实修复时选择“已解决”；接受风险必须留下原因，权限、未授权个人数据和受限数据不得 accepted risk。

![知识看板](images/05-knowledge-dashboard-desktop.png)

## 13. Fact 审核与正式 Evidence 提升

入口：`知识库 → 证据追踪`。

1. 阅读完整 Statement 和来源，不只看标题。
2. 确认事实主体、型号、市场、时效和原文含义。
3. 营销评价、拼接错句、无授权体验、页脚噪音选择“拒绝”。
4. 可追溯事实选择“批准”，备注使用限制。
5. **批准只改变 Fact Candidate 状态，不会自动创建正式 Evidence。**

![事实审核](images/05-knowledge-trace-desktop.png)

批准后展开页面技术信息取得 Fact ID 和正确产品 Entity ID，再执行：

```bash
uv run python scripts/promote_approved_knowledge_fact.py \
  --project-id 983fa88d-097a-4252-9ab3-fc4371799c55 \
  --fact-id '<approved-fact-id>' \
  --subject-entity-id '<v600-entity-id>' \
  --subject-role product --usage-rights owned \
  --confidentiality public --public-disclosure \
  --attribution-required \
  --receipt "artifacts/runs/$RUN_ID/evidence-<fact-id>.json"
```

工具会验证 Fact 已批准、Entity 同项目、Source 为 ready、Statement hash 一致，并防止相同快照重复创建。公开引用必须同时满足公开保密级别、使用权和公开 URL；内部 Evidence 可以用于内部生成，但不能自动成为公开 Citation。

Data Readiness Gate：V600 至少有品牌归属、型号/类别、核心规格和限制条件的可用 Evidence；V1000/SAT30 至少有足以创建 Brief 的产品 Evidence。

## 14. 渠道、政策和 27 个投放任务

入口：`GEO 投放 → 渠道与政策`。

1. 确认九个标准 Destination 均存在，模式为人工投放。
2. 为每个 Destination 记录账号授权、允许 Host、品牌身份、商业披露和平台规则复核时间。
3. Owned Site 可在官方权限确认后 `approved`。
4. YouTube/TikTok/Instagram 需要执行当天重新确认官方账号权限。
5. Amazon 在 Seller 权限确认前保持 `restricted`。
6. ProductReview/Reddit/OzBargain/Quora 没有明确上下文和身份时保持 `restricted`。
7. restricted Opportunity 保持可见的 blocked task，不得删除以制造高完成率。

三产品 × 九渠道必须等于 27 个 Opportunity。Facebook 可选创建为 `other`，不得改变标准分母。

![九渠道任务](images/07-destinations-desktop.png)

## 15. Campaign、消费者问题和监测方案

入口：`GEO 投放 → Campaign`。

每个产品建立独立 Campaign，只绑定一个主产品和九个 Destination。每个 Campaign 至少有 recommendation 和 comparison 两类自然语言 Query。不得把品牌名强行写进所有 Query，否则无法测量消费者自然提问下的可见性。

创建 Monitoring Protocol：填写提供方/模型、地区、语言、无痕会话、每个 Query 重复次数、Baseline/T+28/T+56/T+84 和排除规则。检查后执行批准、冻结。冻结后改变样本口径必须创建新 Protocol Version。

![Campaign 与查询](images/06-campaign-monitoring-desktop.png)

## 16. 录入真实 Baseline

入口：`GEO 投放 → AI 观察`。

1. 选择冻结 Protocol 和其中的 Query。
2. 在指定地区、语言和会话条件下向 AI 搜索工具提问。
3. 原样保存回答、提供方请求 ID、实际模型、采集时间、引用 URL、ADVINSYS 是否出现和推荐位置。
4. 不可访问外网时，真实项目不伪造 Observation；在 Staging 执行第 23 章。
5. 样本达到冻结口径后计算 Baseline Metric。

![观察录入](images/08-observations-desktop.png)

## 17. V600 正式文案生产

### 17.1 内容要求 Brief

入口：`内容生产 → 步骤 1 内容要求`。

选择 V600 Campaign、具体 Opportunity、ADVINSYS 主品牌、V600 产品、en-AU 和目标渠道。填写消费者 Query、目标、卖点、限制、披露和真实消费者描述。消费者描述是一段业务方提供的原始使用描述；系统可据此生成测试或正式文案，但不得把上传授权本身当作体验真实性证明。

保存后生成不可变 Brief Version。修订必须从当前版本创建新版本。

![内容要求](images/09-placement-brief-desktop.png)

### 17.2 Evidence Pack Attempt

入口：`内容生产 → 步骤 2 证据与规则`。点击“构建证据”，等待 Durable Job。

- `ready`：继续。
- `needs_evidence`：补充事实或来源，再创建新 Attempt。
- `blocked`：处理权限、授权、机密、主体冲突或政策。

旧 Attempt 永不重新进入 building；新成功 Attempt 可 supersede 旧 Attempt。

![Evidence Pack](images/10-placement-evidence-desktop.png)

### 17.3 Prompt Release、Binding 和 Bundle

首次点击“同步九平台默认 Prompt”。Prompt 源文件位于仓库 `prompt/`，前端修改时会创建不可变 Release；不会改写历史 Bundle。

修改 Prompt 时必须保留输出字段：`content_json`、`rendered_text`、`claims`、`internal_evidence_refs`、`public_citation_refs`。创建新 Release 后把正确 Channel Binding 指向它；回滚时重新绑定旧 Release。选择 ready Evidence Attempt 和 Release，点击“冻结本次生成输入”。

![Prompt 管理](images/36-prompt-management-current.png)

### 17.4 DeepSeek 生成

入口：`内容生产 → 步骤 3 生成文案`。

1. 选择最新 Bundle。
2. 模型保持 `deepseek-v4-flash`，总调用预算 2。
3. 点击“开始生成”，等待 queued → running → succeeded。
4. 失败先读 Job Events：同输入临时失败用 retry；需要新审计链用 replay/regenerate；输入错误则创建新 Bundle。
5. 成功后核对 provider reported model、token、finish reason、response hash、正文和 Claim。

模型预算包含首次调用、Schema 修复和 fallback，避免 Gateway 与 Job 各自重试造成重复付费。

![生成文案](images/11-placement-generation-desktop.png)

### 17.5 编辑、Claim QA 和独立审核

入口：`内容生产 → 步骤 4 审核定稿`。

人工编辑必须创建新 Asset Version，并基于原 content hash 防并发覆盖；旧审批失效但不删除。新版本重新执行 Claim extraction、QA 和 Review。

Operator 点击“提交独立审核”；不同身份的 Reviewer 核对每个事实性句子，分别确认 `claim_inventory_complete` 和 extracted claim support，评分至少 85 才可批准。unsupported Claim、主体错误、披露缺失或同人审批必须被阻断。

![独立审核](images/12-placement-review-desktop.png)

### 17.6 Export 与 Publication 边界

批准后点击“创建不可变导出”。记录导出前后的 Publication Request 数量，必须不变。导出可用于内部复核、客户、法务或备份，并不表示准备发布。

只有用户在步骤 5 显式点击“标记为待发布”才创建 Publication Request。

## 18. 人工投放、URL 回填和验证

入口：`内容生产 → 步骤 5 发布与测量`。

1. 选择批准版本、Destination 和 publication attempt。
2. 填政策依据；restricted 渠道只有条件真实满足后才确认。
3. 点击“标记为待发布”。
4. 授权人员离开 GEO，登录第三方账号，按批准正文、披露和链接人工发布。
5. 回到 GEO 创建 Submission，保存平台回执或草稿号。
6. 页面公开后回填匿名可访问 URL，再请求验证。
7. Host 必须在 allowlist；页面要可达、正文相符、披露和链接完整。
8. 失败先修复外部页面再验证，不改数据库状态。

URL 未上线时真实 Submission 保持 awaiting URL；账号不可用时 Publication/Opportunity 标记 blocked 并写清 owner 和恢复条件。

![发布与验证](images/15-placement-publication-desktop.png)

## 19. 测量、报告和 T+28/T+56/T+84

验证成功后系统创建三个 Measurement Collection Task。真实项目只在到期且按冻结 Protocol 完成采样后记录 Observation、计算 Metric、完成 Task、生成报告并审批。

`customer_acceptance_satisfied` 定义为“不要求客户验收，或存在有效客户验收”。报告不得用相关性数据声称因果关系。

时间未到时真实任务保持 scheduled；不要提前改时间。受控完整链见第 23 章。

## 20. TEST ONLY 九渠道 Prompt 预演

入口：内容生产右上角“打开 TEST ONLY 预览”。

对九个渠道各运行一次，选择对应 Release、品牌、产品、治理合格 Evidence、受众和输出形式。可选择 synthetic testimonial/fake persona 等测试模式，但产物必须保持 `publication_eligible=false`，不得提交正式审核、导出发布包、创建 Publication Request 或进入 Customer Web。

![TEST ONLY](images/14-placement-simulation-desktop.png)

## 21. 客户端全流程

Customer Web 默认 `http://localhost:3000`，Staging 为 `http://localhost:13000`。

1. 客户输入 Invitation ID 和一次性 Token。
2. 点击“兑换邀请并登录”；成功后 URL 不保留 Token。
3. Summary 查看项目摘要和最新状态。
4. Metrics 查看 Baseline 和各复测窗口趋势。
5. Placements 只显示已验证公开 URL 和窗口。
6. Reports 只显示已批准报告并支持下载。
7. 多项目客户用项目选择器切换。
8. 点击退出后，受保护页面必须重新要求登录。

客户不得看到 Prompt、Evidence 原文、未批准文案、Job、内部成员、仿真数据或其他项目。

![客户摘要](images/16-customer-summary-desktop.png)

![客户指标](images/17-customer-metrics-desktop.png)

![客户投放](images/18-customer-placements-desktop.png)

![客户报告](images/19-customer-reports-desktop.png)

## 22. 可选操作

- Prompt：新建 Skill/Release、切换 Binding、回滚旧 Release、下载 TEST ONLY 工件。
- Job：查看 Events、retry、regenerate、dead-letter replay、cancel；外部模型调用期间不持有数据库锁。
- 内容：人工编辑新版本、needs revision、reject、archive、supersede。
- 发布：block/cancel Publication、修正 Submission URL、重新验证、合法递增 publication attempt。
- 测量：到期完成或明确取消 Collection Task，不删除历史 Measurement。
- 知识：下载原始来源、重处理、禁用 Chunk、接受/解决 Finding、批准/拒绝 Fact。
- 权限：改角色、撤销、重新启用、撤销未使用邀请。
- 渠道：新增 Facebook `other`，或新增市场/产品并创建独立 Campaign。

## 23. 完整 Staging 仿真

在专用、可丢弃的 Acceptance 数据库执行。不得使用当前 development `5432` 或
ADVINSYS staging `55433`；真实 Worker/Relay 不得连接该数据库。

```bash
export RUN_ID="geo-acceptance-$(date -u +%Y%m%dT%H%M%SZ)"
export GEO_ACCEPTANCE_ISOLATION_MARKER=geo-accepted-remediation
cp -n infra/remediation.env.example infra/.env.remediation
docker compose -p geo-accepted-remediation --env-file infra/.env.remediation \
  -f infra/docker-compose.yml up -d postgres migrate
docker compose -p geo-accepted-remediation --env-file infra/.env.remediation \
  -f infra/docker-compose.yml exec -T postgres psql -U geo_installer -d postgres \
  -v marker="$GEO_ACCEPTANCE_ISOLATION_MARKER" -c \
  "ALTER DATABASE geo SET geo.acceptance_isolation_marker TO :'marker';"
uv run python scripts/run_geo_acceptance.py \
  --environment staging --confirm-controlled-simulation \
  --app-database-url postgresql://geo_app_dev:geo_app_dev@127.0.0.1:55434/geo \
  --worker-database-url postgresql://geo_worker_dev:geo_worker_dev@127.0.0.1:55434/geo \
  --admin-database-url postgresql://geo_installer:geo_installer_dev@127.0.0.1:55434/geo \
  --isolation-marker "$GEO_ACCEPTANCE_ISOLATION_MARKER" \
  --manifest docs/target_company/advinsys-geo-project.json \
  --run-id "$RUN_ID" \
  --customer-invitation-output "artifacts/runs/$RUN_ID/staging-customer-invitation.json" \
  --output "artifacts/runs/$RUN_ID/simulation-acceptance-result.json"
```

需要验证真实模型时附加：

```bash
--live-deepseek --deepseek-key-file "$PWD/deepseek_api_key.txt"
```

结果必须声明 `execution_mode=inline_isolated`，记录受控 Adapter 和哈希化环境指纹，
并明确 `production_worker_relay_topology_validated=false`。同时必须包含九个持久任务、
九条 `TEST ONLY` Prompt Simulation、九条 Simulation 均 `publication_eligible=false`、
一个完成的 Owned Site 受控链、Export 未自动发布、Claim inventory 完整、不同审核人、
受控 `.example` URL、T+28/T+56/T+84、4 个 Metric、3 个已批准报告和 Customer 安全投影。
项目名必须带 `[SIMULATION]`。

受控验收会创建独立 Tenant 和 Owner。采集 Admin 页面前，把 Staging Admin 身份切到该 Owner；这里只重建无状态 Web 容器：

```bash
export SIM_OWNER_ID=$(jq -r '.project.owner_identity_id' "artifacts/runs/$RUN_ID/simulation-acceptance-result.json")
export SIM_TENANT_ID=$(jq -r '.project.tenant_id' "artifacts/runs/$RUN_ID/simulation-acceptance-result.json")
GEO_ADMIN_ACTOR_ID="$SIM_OWNER_ID" GEO_ADMIN_TENANT_ID="$SIM_TENANT_ID" \
  docker compose -p geo-advinsys-staging \
  --env-file "artifacts/runs/$RUN_ID/staging.env" -f infra/docker-compose.yml \
  -f infra/compose.staging-operator.yml \
  up -d --force-recreate admin-web
```

采集 Admin/Customer 桌面与移动页面：

```bash
SIM_PROJECT_ID=$(jq -r '.project.project_id' "artifacts/runs/$RUN_ID/simulation-acceptance-result.json")
uv run python scripts/capture_geo_runbook.py \
  --mode simulation --admin-base http://localhost:13001 --customer-base http://localhost:13000 \
  --project-id "$SIM_PROJECT_ID" \
  --acceptance-result "artifacts/runs/$RUN_ID/simulation-acceptance-result.json" \
  --customer-invitation "artifacts/runs/$RUN_ID/staging-customer-invitation.json" \
  --output "artifacts/runs/$RUN_ID/browser-simulation"
rm -f "artifacts/runs/$RUN_ID/staging-customer-invitation.json"
```

浏览器报告必须 `failures=0`，删除一次性邀请文件后才可归档工件。

## 24. 浏览器复查真实项目

```bash
uv run python scripts/capture_geo_runbook.py \
  --mode actual --project-id 983fa88d-097a-4252-9ab3-fc4371799c55 \
  --output "artifacts/runs/$RUN_ID/browser-actual"
```

必须检查桌面 1440×1000 和移动 390×844：无 console error、page error、5xx、横向溢出、按钮遮挡和文字越界。复杂 Prompt、Claim 和政策复核建议用桌面端操作。

## 25. 备份、恢复、升级和回滚

生产备份：

```bash
make backup PROD_ENV=infra/production.env
BACKUP_FILE=/absolute/path/to/backup.tgz \
  make restore-smoke PROD_ENV=infra/production.env
```

开发完整烟测：

```bash
make backup-restore-dev-smoke
```

验收内容：Schema 版本、PostgreSQL 表/项目数量、MinIO 对象数量和逐对象 SHA-256 一致，隔离恢复副本已清理。升级前后各备份一次；迁移失败停止写入并回滚应用镜像，再用恢复烟测确认，不手工跳过迁移。

![备份恢复](images/17-backup-restore.png)

## 26. 日常运维

每日：服务健康、失败/过期租约 Job、Outbox/队列积压、模型失败与成本、URL 验证失败、到期 Measurement Task。  
每周：新增知识来源、开放 Finding、待审 Fact、Evidence 使用权、渠道政策和账号权限。  
每月：OIDC 成员与客户权限、Prompt Binding、备份恢复抽测、Secret 轮换计划、报告口径和数据保留。

常用诊断：

```bash
docker compose -f infra/docker-compose.yml --profile workers ps
docker compose -f infra/docker-compose.yml --profile workers logs --tail=300 \
  internal-api customer-api task-worker outbox-relay admin-web customer-web
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:8001/health
```

## 27. 异常处理矩阵

| 现象 | 判断 | 处理 | 终态证据 |
| --- | --- | --- | --- |
| 页面无响应/Application error | Web/API 日志、console、5xx | 记录完整 URL/时间/动作；恢复服务；重跑浏览器脚本 | browser report 无错误 |
| 403 | Session、角色、项目 membership | Owner 修正授权；不传客户端 actor 冒充 | 正确身份可访问 |
| 409 | 状态、版本、content hash 冲突 | 刷新后基于最新版本重做 | 新版本 lineage |
| Knowledge URL 失败 | DNS、TLS、反爬、登录墙、5 MB | 使用授权导出文件/文本；保存来源和时间 | 新 Run succeeded |
| Pipeline 长期 running | Worker、Outbox、lease_expires_at | 恢复 Worker，由系统接管过期租约 | Job event 显示重新领取 |
| Chunk 噪音或串产品 | 清洗和来源页面结构 | 禁用错误 Chunk；修正来源并重处理 | active Chunk 可检索 |
| Fact 无法进入生成 | 是否仅 approved、是否已正式提升 | 执行 Fact→Evidence 工具，核对 rights/citation | Evidence receipt |
| Evidence needs_evidence | 覆盖、主体、rights、citation | 补来源/事实，创建新 Attempt | 新 Attempt ready |
| Evidence blocked | 权限、机密、授权、主体冲突 | 解除阻断或终止，不把 blocked 当可重试事实缺失 | blocker owner |
| DeepSeek 失败 | Key、网络、限流、Schema、预算 | 临时错误 retry；输入错误新 Bundle；预算超限人工审批 | model call log |
| 审核不能批准 | 身份、分数、两项确认、unsupported Claim | 更换独立 Reviewer 或创建修订版本 | Review 决策 |
| Export 后出现发布任务 | Export/Publication 边界回归 | 停止发布，记录缺陷；不得继续 | 数量差异为 0 |
| Publication 无账号 | 权限/平台政策 | blocked 并填写 owner/恢复条件；Staging 仿真 | blocked task |
| URL 验证失败 | allowlist、SSRF、重定向、404、正文、披露 | 修复真实页面，再请求验证 | Verification Job |
| T+28 未到 | due_at | 保持 scheduled；只在 Staging 受控完成 | 两轨回执 |
| 客户看不到数据 | 邀请、项目、approved report、verified URL | 修正投影前置状态，不开放内部 API | Customer 截图 |
| 客户看到内部数据 | 投影或 RLS 缺陷 | 立即停用客户访问，按安全事件处理 | 修复与回归报告 |
| DB/MinIO/Valkey 故障 | 健康、磁盘、连接、凭据 | 停止写入，恢复依赖和 Worker，再核对 Job | 健康与一致性回执 |
| 迁移/恢复失败 | Schema、dump、对象 hash | 保留原环境，修复隔离副本；不得覆盖生产 | restore receipt |

同一错误连续出现三次时停止盲目重试，保留 correlation ID、Job ID、输入 hash 和日志，升级给模块 Owner。任何时候都不得在故障材料中包含 Secret。

## 28. 最终交付清单

- [ ] 真实项目 1 品牌、3 产品、1 市场、9 Destination、3 Campaign、27 Opportunity、6 Query。
- [ ] 六个知识来源有终态；Chunk、检索、Finding 和 Fact 已人工治理。
- [ ] 选定 Fact 已通过正式 Evidence 提升，主体、使用权和公开 Citation 正确。
- [ ] V600 完成 ready Evidence Pack、Prompt Bundle、真实 DeepSeek Job、Asset、Claim QA 和独立审核。
- [ ] Export 未创建 Publication Request；发布意图由用户显式创建。
- [ ] 九渠道都有任务，受限渠道保持可见 blocker。
- [ ] 真实 URL/Observation/Metric 只来自真实操作。
- [ ] 独立 Staging 完成受控 URL、T+28/T+56/T+84、报告和 Customer 四视图。
- [ ] 客户只能看到 verified/approved 投影。
- [ ] 桌面/移动浏览器报告失败数为 0。
- [ ] PostgreSQL 和 MinIO 备份恢复烟测通过。
- [ ] `actual-provision-receipt.json` 与 `simulation-acceptance-result.json` 均已归档。
- [ ] 手册 Markdown、全部图片和 PDF 已通过链接、页数、图片嵌入及文字提取检查。

只有以上项目全部满足，才能将系统功能验收标记为完成。真实第三方投放仍应逐条以其真实状态交付，不能用 Staging 完成态替代。
