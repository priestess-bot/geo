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

必需变量：

```bash
export GOOGLE_PLAYWRIGHT_ENABLED=1
export MANUAL_BACKFILL_PATH=/absolute/path/to/google-ai-mode-manual-backfill.jsonl
export DATABASE_URL=postgresql://...
```

推荐变量：

```bash
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

3. 做 collector health-only 预检：

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

4. 运行真实 240-run spike：

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

5. 汇总状态：

```bash
make au-p0b-google-status
make verify-au-p0b-google-status
```

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

2. 接入真实供应商前做 health-only 预检：

```bash
make au-p0b-google-serp-health
```

默认输出：

```text
docs/runtime_preflight/au-p0b-google-serp-health-latest.json
```

若缺少 `SERP_API_KEY` 或 `SERP_API_ENDPOINT`，该目标会以 collector health gate fail 退出，并在 payload 中给出 `google.third_party_serp:not_configured` 或 endpoint 相关原因。health 通过后再用显式 worker 命令运行真实对照：

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

## 4. 停止条件

- `verify-au-p0b-google-runbook` 失败：停止，先修步骤顺序、planned runs、gate 参数或 runbook hash。
- dry-run verifier 失败：停止，先修 runbook execution payload 或环境判断。
- health-only collector gate 失败：停止，先修 `GOOGLE_PLAYWRIGHT_ENABLED`、`MANUAL_BACKFILL_PATH`、浏览器账号/selector 或人工补录文件。第三方对照切片另需检查 `SERP_API_KEY` 与 `SERP_API_ENDPOINT`。
- 真实 spike 出现 collection failure：停止，先复盘 `failure_events` 和 `CollectionRunSummary`。
- `google_spike_gate` 失败：Google 不进入主评分，只进入 limited coverage 附录。
- `google_spike_readiness_gate` 失败：即使 AIO 成功率达标，也不能进入主评分。
- status report 的 `next_action` 不是 `allow_google_into_main_scoring_denominator`：停止，按 `remaining_blockers` 逐项处理。

## 5. 产物

- `docs/runtime_preflight/au-p0b-google-spike-runbook-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-runbook-execution-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-health-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-health-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-manifest-latest.json`
- `docs/runtime_preflight/au-p0b-google-spike-status-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-fixture-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-health-latest.json`
- `docs/runtime_preflight/au-p0b-google-serp-latest.json`

真实运行后，应保留 gitignored JSON 产物用于本地复盘，并把摘要写回 `docs/工程实施审计日志.md`。

## 6. 当前边界

本手册固定真实 Google spike 的可审计执行路径，不代表已经完成真实 Playwright 采集、真实 AI Mode 浏览器采集、真实第三方供应商凭证联调或 240-run 真实样本。当前第三方路径是通用 JSON adapter，不绑定单一供应商私有 schema；若选定供应商有更稳定的专用字段，应在保持 `RawCollectResult`、snapshot hash、`answer_present/surface_triggered` 语义不变的前提下新增轻量 mapping，并通过独立 120-run 对照切片进入 P0b 复盘。第三方对照结果不能绕过 `GoogleSpikeGateResult`、`GoogleSpikeReadinessGate` 和 `score_input_policy`。
