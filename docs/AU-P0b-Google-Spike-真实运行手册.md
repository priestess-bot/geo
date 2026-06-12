# AU P0b Google Spike 真实运行手册

本文档描述 Google AI Overviews / AI Mode 高风险 spike 的真实运行路径。机器可读版本由 `make au-p0b-google-runbook` 生成，默认写入 gitignored 的 `docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json`；执行预演由 `make au-p0b-google-runbook-dry-run` 生成；阶段状态由 `make au-p0b-google-status` 汇总。

## 1. 目标

P0b 不追求一开始把 Google 全量纳入主评分，而是先给出可复盘的 pass/fail 结论：

- Google AIO / AI Mode 是否能完成 30 条高意图 prompt。
- 地理范围是否覆盖 Australia + Sydney。
- 每条 prompt 重复采样 k=2。
- 至少观察到两条采集路径：browser / third_party_api / manual 三选二。
- 每条成功结果必须有 screenshot 或 HTML snapshot。
- 如果 `google_spike_gate` 和 `google_spike_readiness_gate` 没有同时通过，Google 只能进入 limited coverage 附录，不进入主评分分母。

当前工程默认真实路径为：

```text
google_aio     -> PlaywrightGoogleAIOCollector -> access_method=browser
google_ai_mode -> ManualBackfillCollector      -> access_method=manual
```

`ThirdPartySerpCollector` 已作为 provider-neutral JSON adapter 落地，但不进入默认 240-run 核心矩阵。它可通过 `SERP_API_KEY` / `SERP_API_ENDPOINT` 调用第三方 SERP/AI-answer 服务，解析常见 `ai_overview`、`answer_box`、`organic_results`、`inline_results` 字段，生成 HTML snapshot hash。普通 organic-only 响应只算 `answer_present`，不算 AIO `surface_triggered`。当前第三方路径已拆为独立 `google-serp-fixture` / `google-serp-spike` 对照模式，计划口径为 30 prompts × Australia/Sydney × k=2 × 1 third-party backend = 120 planned runs；它输出 `google_serp_comparison_plan` 与 `google_serp_comparison_summary`，`--persist` 时只保存 raw evidence 与 `CollectionRunSummary(run_type=google_serp_comparison)`，不允许 `--persist-analysis`，避免同一 prompt/city/sample 多后端结果重复进入主评分分母。

## 2. 运行前环境

推荐先复制脱敏模板：

```bash
cp .env.au-p0b-google.example .env.au-p0b-google
```

模板默认 `GOOGLE_PLAYWRIGHT_ENABLED=0`，不会误触发真实浏览器采集。填完真实 selector、storage state、manual backfill 路径、数据库和可选对象存储后，再运行 `make au-p0b-google-playwright-env`；报告只会保存变量来源、长度和 hash 前缀，不会保存原始值。

必需变量：

```bash
export GOOGLE_PLAYWRIGHT_ENABLED=1
export MANUAL_BACKFILL_PATH=/absolute/path/to/google-ai-mode-manual-backfill.jsonl
export DATABASE_URL=postgresql://...
```

推荐变量：

```bash
export GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR='textarea[name="q"]'
export GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR='[data-attrid*="AI"], [data-testid*="answer"]'
export GOOGLE_PLAYWRIGHT_SUBMIT_SELECTOR=
export GOOGLE_PLAYWRIGHT_CITATION_SELECTOR='a[href^="http"]'
export GOOGLE_PLAYWRIGHT_STORAGE_STATE=/absolute/path/to/google-storage-state.json
export GOOGLE_AIO_PLAYWRIGHT_START_URL='https://www.google.com/search?udm=14'
export GOOGLE_AI_MODE_PLAYWRIGHT_START_URL='https://www.google.com/search?udm=50'
export GOOGLE_PLAYWRIGHT_BROWSER_NAME=chromium
export GOOGLE_PLAYWRIGHT_TIMEOUT_SECONDS=45
export GOOGLE_PLAYWRIGHT_VENDOR_COST=0.004
export SERP_API_ENGINE=google_ai_overview
export SERP_API_KEY=...
export SERP_API_ENDPOINT=https://your-serp-provider.example/search
export SERP_API_GL=au
export SERP_API_HL=en
export SERP_API_LOCATION=Australia
export SERP_API_VENDOR_COST=0.006
export OBJECT_STORE_ENDPOINT=...
export OBJECT_STORE_BUCKET=...
export OBJECT_STORE_ACCESS_KEY=...
export OBJECT_STORE_SECRET_KEY=...
export GENO_BROWSER_ARTIFACT_DIR=/absolute/path/to/browser-artifacts
```

`PlaywrightGoogleAIOCollector` 和 `PlaywrightAIModeCollector` 已是 selector-driven browser adapter：health-only 预检会在真实采集前检查 `GOOGLE_PLAYWRIGHT_ENABLED`、prompt/answer selector、可选 storage state 文件和 Python Playwright 包。常见失败原因包括 `selector_missing`、`session_state_missing`、`playwright_missing`。通过后，collector 会记录最终 URL、页面标题、HTML snapshot hash、screenshot hash、citation selector 提取结果和 `google-playwright-browser-v1` collector version。上面的 selector 只是模板，真实运行前必须用澳洲 Google 账号、AU IP/地理环境和目标界面手工校准。

真实 240-run 前必须先跑 Google Playwright 单样本 smoke。`au-p0b-google-playwright-smoke` 会选择 P0b 高意图 prompt 的第一条，在 Sydney / desktop 下采一条 browser evidence，并写入 `smoke_payload_hash`。`verify-au-p0b-google-playwright-smoke` 默认只校验 payload hash、结构和失败原因可审计；最终晋级 browser path 前必须使用 `--require-success`，要求真实 browser capture 成功、`answer_present/surface_triggered=true`、存在 HTML/screenshot hash、`_geno_browser_capture.capture_type=google_browser_ui` 和 `answer_run_collected` 审计事件。

`ManualBackfillCollector` 已支持读取 `MANUAL_BACKFILL_PATH` 指向的 JSONL 文件。每行是一条人工补录证据，最小字段如下；同一 `prompt + city` 的多条记录会按 worker 调用顺序消费，用于 k=2 样本：

```json
{"prompt":"原始 prompt 文本","city":"Sydney","language":"en-AU","device":"desktop","answer_text":"人工记录的 Google AI Mode 答案","citation_urls":["https://example.com/source"],"screenshot_url":"s3://.../manual.png","html_snapshot_url":"s3://.../manual.html","submitted_by":"analyst@example.com","notes":"AI Mode manual sample 1"}
```

兼容字段：`prompt_text` / `question` 可替代 `prompt`，`answer` / `content` 可替代 `answer_text`，`citations` / `sources` 可用字符串数组或 `{ "url": "..." }` 对象数组。health-only 预检会检查文件存在；真实采集时若 JSONL 为空、JSON 无效、目标 prompt/city 缺记录或缺 `answer_text`，worker 会把该样本写成可审计 collection failure。

生成待填模板和校验文件覆盖率：

```bash
make au-p0b-google-manual-template
MANUAL_BACKFILL_PATH=/absolute/path/to/google-ai-mode-manual-backfill.jsonl \
  make verify-au-p0b-google-manual-backfill
```

`au-p0b-google-manual-template` 会生成 120 行模板：30 prompts × Australia/Sydney × k=2，只覆盖 `google_ai_mode` manual path。模板本身允许 `answer_text`、citation 和资产为空；真实运行前必须用 `verify-au-p0b-google-manual-backfill` strict 校验通过，它会要求 120 行全部填充、每个 prompt/city 有 2 条样本、每行有 answer、至少一个 citation、以及 screenshot 或 HTML snapshot 资产。该校验会把结果写入 `docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json`，其中包含原始 JSONL 的 `file_sha256` 和 verification 自身的 `verification_hash`，供 status report 离线复算。

所有运行产物默认写入 `docs/runtime_preflight/*.json`，该目录下 JSON 默认不提交，避免把真实 provider 状态、错误上下文或潜在敏感配置写入仓库。需要提交的是摘要、审计日志和代码。

## 3. 标准步骤

1. 生成机器可读 runbook：

```bash
make au-p0b-google-runbook
make verify-au-p0b-google-runbook
```

2. 先做 dry-run，不触发真实 Google：

```bash
make au-p0b-google-runbook-dry-run
make verify-au-p0b-google-runbook-execution
```

3. 生成 Google Playwright 环境 readiness 报告：

```bash
make au-p0b-google-playwright-env
make verify-au-p0b-google-playwright-env
```

默认输出：

```text
docs/runtime_preflight/au-p0b-google-playwright-env-latest.json
```

该报告会读取 P0b runbook、`.env.au-p0b-google` 和当前进程环境，只保存变量存在状态、来源、长度和 sha256 前缀，不保存原始 secret 或 selector。关键字段包括 `ready_for_playwright_smoke`、`ready_for_full_google_run`、`collector_health`、`missing_required`、`missing_selector_groups`、storage state 文件检查、Python Playwright 包检查和 `next_action`。默认 verifier 只证明报告 hash、脱敏结构和状态推导可复算；真实 smoke 前可用 strict gate：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/verify_au_p0b_google_playwright_env_report.py \
  docs/runtime_preflight/au-p0b-google-playwright-env-latest.json \
  --require-ready-smoke
```

4. 运行 Google Playwright 单样本 smoke：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/run_au_p0b_google_playwright_smoke.py \
  --output-path docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json

make verify-au-p0b-google-playwright-smoke
```

如果 smoke runner 因 health gate 失败退出，脚本仍会先写入失败 payload。需要复盘失败原因时可直接运行 verifier；需要把 browser path 提升到 240-run 前置条件时必须执行 strict gate：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/verify_au_p0b_google_playwright_smoke.py \
  docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json \
  --require-success
```

5. 校验 Google AI Mode manual backfill 严格覆盖：

```bash
make verify-au-p0b-google-manual-backfill
```

默认输入为 `MANUAL_BACKFILL_PATH`；未设置时会读取 `docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl`。默认输出：

```text
docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json
```

只有 strict verifier 通过、verification hash 可复算，并且 status report 读取到该 artifact 后，才允许继续进入 collector health-only 和 240-run。

6. 做 collector health-only 预检：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode google-spike \
  --require-ready-collectors \
  --health-check-only \
  --preflight-output-path docs/runtime_preflight/au-p0b-google-spike-health-latest.json

PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/build_preflight_manifest.py \
  docs/runtime_preflight/au-p0b-google-spike-health-latest.json \
  --manifest-path docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json
```

7. 运行真实 240-run spike：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode google-spike \
  --require-ready-collectors \
  --require-no-collection-failures \
  --require-google-spike-gates \
  --persist \
  --preflight-output-path docs/runtime_preflight/au-p0b-google-spike-latest.json

PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/build_preflight_manifest.py \
  docs/runtime_preflight/au-p0b-google-spike-latest.json \
  --manifest-path docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json
```

8. 汇总状态：

```bash
make au-p0b-google-status
make verify-au-p0b-google-status
```

`au-p0b-google-status` 会读取 runbook、dry-run execution、Playwright env readiness、Playwright smoke、manual backfill strict verification、health、spike 和 manifest 产物。若 env readiness 报告缺失，状态报告会输出 `next_action=run_google_playwright_env_report`；若 env strict gate 不通过，会优先返回 env 报告里的 `next_action`，例如补 selector、storage state 或 Playwright 包。若 Playwright smoke 没有通过 strict success gate，状态报告会输出 `next_action=run_google_playwright_smoke`，并把 `playwright_smoke:smoke_not_successful` 或对应文件/hash/结构错误放入 `remaining_blockers`。若 manual verification 缺失或 strict 失败，状态报告会输出 `next_action=run_verify_google_manual_backfill`、`prepare_google_manual_backfill_file` 或 `fix_google_manual_backfill_coverage`；这时不要进入 health-only 或 240-run。

需要硬门禁时：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/verify_au_p0b_google_spike_status_report.py \
  docs/runtime_preflight/au-p0b-google-spike-status-latest.json \
  --require-google-main-scoring-allowed
```

## 3.1 第三方 SERP 独立对照切片

第三方 SERP 对照切片用于验证供应商是否能补充 Google AIO 证据，不替代默认 `google-spike` 240-run 核心矩阵，也不单独证明 Google 可以进入主评分分母。

1. 先运行 fixture，复核 120-run 计划口径、summary 与持久化边界：

```bash
make au-p0b-google-serp-fixture
make verify-au-p0b-google-serp-fixture
make au-p0b-google-serp-fixture-manifest
```

默认输出：

```text
docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json
```

关键字段：

```text
google_serp_comparison_plan.planned_runs = 120
google_serp_comparison_plan.main_google_spike_planned_runs = 240
google_serp_comparison_summary.ready_for_comparison = true
google_spike_gate / google_spike_readiness_gate 不应出现在该模式输出中
```

`verify-au-p0b-google-serp-fixture` 会要求 `ready_for_comparison=true`、collector health pass、payload hash 可复算、120-run 计划口径正确、full Google spike gates 不存在，以及 score input policy 保持 comparison-only。

2. 接入真实供应商前做 health-only 预检：

```bash
make au-p0b-google-serp-health
make verify-au-p0b-google-serp-health
make au-p0b-google-serp-health-manifest
```

默认输出：

```text
docs/runtime_preflight/au-p0b-google-serp-health-latest.json
```

若缺少 `SERP_API_KEY` 或 `SERP_API_ENDPOINT`，该目标会以 collector health gate fail 退出，并在 payload 中给出 `google.third_party_serp:not_configured` 或 endpoint 相关原因；这种失败 payload 仍可通过 `verify-au-p0b-google-serp-health` 证明 hash、计划口径和审计结构完整，但不会被标记为 comparison ready。health 通过后再用显式 worker 命令运行真实对照：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode google-serp-spike \
  --require-ready-collectors \
  --require-no-collection-failures \
  --persist \
  --preflight-output-path docs/runtime_preflight/au-p0b-google-serp-latest.json
```

禁止在该模式使用 `--persist-analysis`；真实 third-party 结果只能作为 comparison evidence，待与完整 `GoogleSpikeGateResult` 和 `GoogleSpikeReadinessGate` 复盘后，才讨论是否调整主评分准入口径。

3. 汇总第三方 SERP 对照状态：

```bash
make au-p0b-google-serp-status
make verify-au-p0b-google-serp-status
```

`au-p0b-google-serp-status` 会汇总 fixture、fixture manifest、supplier health、health manifest、真实 comparison payload 与 comparison manifest，输出 `comparison_evidence_ready`、`supplier_health_ready`、`remaining_blockers` 和 `next_action`。即使该 status pass，也只表示 third-party SERP evidence 可进入 P0b review，不表示 Google 可以进入主评分分母；主评分仍必须由默认 `google-spike` 240-run 的 `GoogleSpikeGateResult`、`GoogleSpikeReadinessGate` 和 `score_input_policy` 决定。

## 4. 停止条件

- `verify-au-p0b-google-runbook` 失败：停止，先修步骤顺序、planned runs、gate 参数或 runbook hash。
- dry-run verifier 失败：停止，先修 runbook execution payload 或环境判断。
- Google Playwright env strict verifier 失败：停止，先按 `next_action` 修 `GOOGLE_PLAYWRIGHT_ENABLED`、prompt/answer selector、storage state 文件、Python Playwright 包、runbook 或 `.env.au-p0b-google`。
- Google Playwright smoke strict verifier 失败：停止，先修 selector、session state、Playwright 安装、AU 地理环境、目标界面入口或账号状态，不进入 240-run。
- Google manual backfill strict verifier 失败：停止，先修 `MANUAL_BACKFILL_PATH`、120 行覆盖、每个 prompt/city 两条样本、answer、citation 和 screenshot/HTML 资产；没有通过 `manual_backfill_verification_json` 前不进入 health-only 或 240-run。
- health-only collector gate 失败：停止，先修 `GOOGLE_PLAYWRIGHT_ENABLED`、`GOOGLE_PLAYWRIGHT_PROMPT_SELECTOR`、`GOOGLE_PLAYWRIGHT_ANSWER_SELECTOR`、Playwright 安装、可选 storage state、`MANUAL_BACKFILL_PATH` 或人工补录文件。第三方对照切片另需检查 `SERP_API_KEY` 与 `SERP_API_ENDPOINT`。
- 真实 spike 出现 collection failure：停止，先复盘 `failure_events` 和 `CollectionRunSummary`。
- `google_spike_gate` 失败：Google 不进入主评分，只进入 limited coverage 附录。
- `google_spike_readiness_gate` 失败：即使 AIO 成功率达标，也不能进入主评分。
- status report 的 `next_action` 不是 `allow_google_into_main_scoring_denominator`：停止，按 `remaining_blockers` 逐项处理。

## 5. 产物

- `docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json`
- `docs/runtime_preflight/au-p0b-google-playwright-env-latest.json`
- `docs/runtime_preflight/au-p0b-google-playwright-smoke-latest.json`
- `docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-health-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-status-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-fixture-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-health-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-health-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-status-latest.json`

真实运行后，应保留 gitignored JSON 产物用于本地复盘，并把摘要写回 `docs/工程实施审计日志.md`。

## 6. 当前边界

本手册固定真实 Google spike 的可审计执行路径。当前 `PlaywrightGoogleAIOCollector` / `PlaywrightAIModeCollector` 已具备 selector-driven browser capture、health gate、HTML/screenshot hash、fake-browser 合同测试、脱敏环境 readiness 报告和单样本 smoke runner/verifier，但不代表已经完成澳洲真实 Google 账号、真实 selector、真实 AI Mode 入口、第三方供应商凭证联调或 240-run 真实样本。当前第三方路径是通用 JSON adapter，不绑定单一供应商私有 schema；若选定供应商有更稳定的专用字段，应在保持 `RawCollectResult`、snapshot hash、`answer_present/surface_triggered` 语义不变的前提下新增轻量 mapping，并通过独立 120-run 对照切片进入 P0b 复盘。第三方对照结果不能绕过 `GoogleSpikeGateResult`、`GoogleSpikeReadinessGate` 和 `score_input_policy`。
