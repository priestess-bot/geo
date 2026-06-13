# AU P0a 真实批次运行手册

本文档描述真实 Perplexity/OpenAI key 到位后，从最小 preflight 到完整 AU P0a 批次的执行顺序、产物命名和停止条件。机器可读版本由 `make au-p0a-runbook` 生成，默认写入 gitignored 的 `docs/runtime_preflight/au-p0a-runbook-latest.json`，由 `make verify-au-p0a-runbook` 校验；`make au-p0a-runbook-dry-run` 会先输出不执行外部调用的执行预演，再由 `make au-p0a-readiness` 输出阶段性 readiness 结果。

## 运行原则

- 先跑最小 preflight，再跑 small batch，最后跑 full batch。
- 每一步都必须先生成 JSON，再 verify，再 manifest。
- runbook 自身也必须先 verify，避免命令顺序、planned runs 或 gate 参数漂移。
- 复制或填写真实 `.env.au-p0a` 前，必须先运行 `make verify-au-p0a-env-template`，确认提交到仓库的 `.env.au-p0a.example` 完整且不含真实 provider secret。
- 真实执行前先跑 runbook dry-run，确认步骤、产物、外部 API 调用风险和环境缺口；dry-run 默认读取 `GENO_AU_P0A_ENV_FILE` 或 `.env.au-p0a`，按进程环境优先、文件只补缺的规则判断 readiness，且默认不执行任何命令。
- 每个阶段开始前都先跑 readiness gate，缺 key、缺上游 manifest 或上游未达 design-partner ready 时停止。
- readiness 默认读取 `GENO_AU_P0A_ENV_FILE` 或 `.env.au-p0a`，按进程环境优先、文件只补缺的规则判断必需变量；默认不主动连接数据库，真实批次前建议开启 `GENO_AU_P0A_REQUIRE_DB_CHECK=1`，用只读 `SELECT 1` 验证合并后的 `DATABASE_URL` 可用。
- “可审计”不等于“可进入 design partner”；进入下一阶段必须通过 `--require-design-partner-ready`。
- live 运行产物位于 `docs/runtime_preflight/*.json`，默认不提交，避免把 provider 状态、错误上下文或潜在敏感配置写入仓库。

## 命令顺序

1. 生成机器可读 runbook：

```bash
make au-p0a-runbook
make verify-au-p0a-runbook
```

2. 校验模板并准备环境：

```bash
make verify-au-p0a-env-template
cp .env.au-p0a.example .env.au-p0a
chmod 600 .env.au-p0a
```

再把 `.env.au-p0a` 中的 provider key、数据库连接和对象存储配置替换为真实值，或直接在 shell 中导出变量：

```bash
export PERPLEXITY_API_KEY=...
export OPENAI_API_KEY=...
export DATABASE_URL=...
```

推荐同时配置对象存储：

```bash
export OBJECT_STORE_ENDPOINT=...
export OBJECT_STORE_BUCKET=...
export OBJECT_STORE_ACCESS_KEY=...
export OBJECT_STORE_SECRET_KEY=...
```

3. 生成环境报告和执行预演：

```bash
make au-p0a-env
make verify-au-p0a-env
make au-p0a-environment-checklist
make verify-au-p0a-environment-checklist
python3 scripts/verify_au_p0a_env_report.py --require-ready-environment
GENO_AU_P0A_ENV_FILE=${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} make au-p0a-runbook-dry-run
make verify-au-p0a-runbook-execution
GENO_AU_P0A_ENV_FILE=${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} GENO_AU_P0A_REQUIRE_DB_CHECK=1 make au-p0a-readiness
```

4. 最小 provider preflight：

```bash
make api-preflight
make verify-api-preflight
make preflight-manifest
GENO_AU_P0A_ENV_FILE=${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} GENO_AU_P0A_READINESS_PHASE=small_batch make au-p0a-readiness
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/verify_preflight_payload.py \
  docs/runtime_preflight/api-preflight-latest.json \
  --require-design-partner-ready
```

5. 小批次真实采集（默认 5 prompts x Sydney x k=3 x 2 platforms = 30 runs）：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode api \
  --prompt-limit 5 \
  --cities Sydney \
  --sample-size 3 \
  --require-ready-collectors \
  --require-p0a-readiness \
  --require-no-collection-failures \
  --preflight-output-path docs/runtime_preflight/au-p0a-small-batch.json \
  --persist \
  --persist-analysis

PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/build_preflight_manifest.py \
  docs/runtime_preflight/au-p0a-small-batch.json \
  --manifest-path docs/runtime_preflight/au-p0a-small-batch-manifest.json \
  --require-design-partner-ready

GENO_AU_P0A_ENV_FILE=${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} GENO_AU_P0A_READINESS_PHASE=full_batch make au-p0a-readiness
```

6. 完整 AU P0a 批次（默认 100 prompts x 4 geo x k=3 x 2 platforms = 2400 runs）：

```bash
PYTHONPATH=packages/geno_core:apps/api \
python3 workers/collector_worker/run_collection_slice.py \
  --mode api \
  --prompt-limit 100 \
  --cities Australia,Sydney,Melbourne,Brisbane \
  --sample-size 3 \
  --require-ready-collectors \
  --require-p0a-readiness \
  --require-no-collection-failures \
  --preflight-output-path docs/runtime_preflight/au-p0a-full-batch.json \
  --persist \
  --persist-analysis

PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/build_preflight_manifest.py \
  docs/runtime_preflight/au-p0a-full-batch.json \
  --manifest-path docs/runtime_preflight/au-p0a-full-batch-manifest.json \
  --require-design-partner-ready

make au-p0a-package
make verify-au-p0a-package
GENO_AU_P0A_ENV_FILE=${GENO_AU_P0A_ENV_FILE:-.env.au-p0a} make au-p0a-status
make verify-au-p0a-status
make au-p0a-execution-checklist
make verify-au-p0a-execution-checklist
```

## 停止条件

- provider health 不是 `ready`：停止，先修 key、collector 配置或 provider 可用性。
- `P0ACollectionReadinessGate` 未通过：停止，不进入下一阶段。
- `--require-no-collection-failures` 返回非零：停止，先复盘失败样本和重试/限流策略。
- manifest verifier `status=fail`：停止，先修 payload 完整性、必备字段或 gate 状态。
- runbook verifier `status=fail`：停止，先修命令计划、planned runs、gate 参数或 runbook hash。
- runbook dry-run `status=fail` 或步骤/产物不符合预期：停止，先修 runbook 或执行参数；默认 dry-run 不会调用外部 provider。
- readiness verifier `status=fail`：停止，先修必需环境、上游 payload、manifest 或 design-partner gate。
- `database.connection_check=fail`：停止，先修 `DATABASE_URL`、网络、凭证或迁移后的 PostgreSQL 服务。
- `ready_for_design_partner=false`：停止，不进入 design partner 或 full batch。
- status report `next_action` 不是 `ready_for_design_partner_handoff`：停止，按 `remaining_blockers` 逐项修复。
- execution checklist `ready_for_design_partner=false`：停止，按 `remaining_blockers` 和 `execution_commands` 补齐真实环境、preflight、小批次或全量批次证据。

## 产物清单

默认产物路径：

- `docs/runtime_preflight/api-preflight-latest.json`
- `docs/runtime_preflight/api-preflight-manifest-latest.json`
- `docs/runtime_preflight/au-p0a-runbook-latest.json`
- `docs/runtime_preflight/au-p0a-env-latest.json`
- `docs/runtime_preflight/au-p0a-environment-checklist-latest.json`
- `docs/runtime_preflight/au-p0a-runbook-execution-latest.json`
- `docs/runtime_preflight/au-p0a-readiness-latest.json`
- `docs/runtime_preflight/au-p0a-evidence-package-latest.json`
- `docs/runtime_preflight/au-p0a-status-latest.json`
- `docs/runtime_preflight/au-p0a-execution-checklist-latest.json`
- `docs/runtime_preflight/au-p0a-small-batch.json`
- `docs/runtime_preflight/au-p0a-small-batch-manifest.json`
- `docs/runtime_preflight/au-p0a-full-batch.json`
- `docs/runtime_preflight/au-p0a-full-batch-manifest.json`

每份 manifest 必须记录：

- preflight/batch JSON path、size 和 file sha256
- payload hash 与 verifier computed hash
- phase、exit code、planned/record/success/failure counts
- blocking reasons、worker args 和 evidence refs
- manifest_payload_hash

runbook verifier 必须确认：

- runbook_payload_hash 可复算
- preflight、small batch、full batch 步骤顺序固定
- small batch planned runs = 30，full batch planned runs = 2400
- design partner gate、P0a readiness gate 和 no-collection-failures gate 未缺失

environment report 必须确认：

- environment_report_hash 可由 `make verify-au-p0a-env` 复算
- `PERPLEXITY_API_KEY`、`OPENAI_API_KEY`、`DATABASE_URL` 必需变量只记录存在状态、来源、长度和 sha256 前缀，不输出原始 secret
- `.env.au-p0a` 可作为本地 secret 文件，真实 `.env.au-p0a` 不提交 git；`GENO_AU_P0A_ENV_FILE` 可指向其它本地 secret 文件
- env-file hygiene 会记录 `exists/entry_count/inside_workspace/git_ignored/git_tracked/file_mode/permission_safe/hygiene_ready/errors/warnings`，不记录原始值；当本地 env 文件存在且含条目时，必须保持 gitignored、not tracked，并设置为 `0600`，否则 `ready_for_real_batch` 为 false
- 如果完全通过进程环境注入 secret，`.env.au-p0a` 缺失不会触发 env-file hygiene hard error
- `ready_for_real_batch` 只在 runbook verifier 通过、必需环境存在且 env-file hygiene 通过时为 true

env template verifier 必须确认：

- `template_verification_hash` 可由 `make verify-au-p0a-env-template` 复算
- `.env.au-p0a.example` 包含 `PERPLEXITY_API_KEY`、`OPENAI_API_KEY`、`DATABASE_URL` 和 P0a runtime 输出路径
- provider key 在模板中必须为空；`DATABASE_URL` 和对象存储凭证只能是本地占位值
- 输出路径必须落在 gitignored 的 `docs/runtime_preflight/*.json`
- 模板报告只输出长度、sha256 前缀和脱敏状态，不输出原始值；出现 `sk-`、`pplx-`、`AIza` 或 `serpapi.com` 等疑似真实 secret 标记时必须 fail
- 该 verifier 只证明已提交模板安全完整，不证明本地 `.env.au-p0a`、真实 provider key 或数据库已 ready

environment checklist 必须确认：

- environment_checklist_hash 可由 `make verify-au-p0a-environment-checklist` 复算
- 必填变量、推荐变量、present/source/value_length/sha256_prefix 与 env report 一致
- `env_file_hygiene` 摘要与 env report 一致，summary 必须包含 `env_file_hygiene_ready` 和 `env_file_hygiene_error_count`
- 不包含 `value` 或 `raw_value` 等原始 secret 字段
- setup_commands 固定 env 模板校验、env 模板复制、runbook、env report 和 checklist 生成顺序
- verification_commands 固定 `--require-ready-environment`、runbook dry-run、DB readiness 和 status refresh
- 当前缺项可直接回答 `p0a_environment` work item 还要填哪些输入

runbook dry-run 必须确认：

- execution_version 为 `au_p0a_runbook_execution_v1`
- execution_payload_hash 可由 `make verify-au-p0a-runbook-execution` 复算
- 默认 `mode=dry_run`、`executed_command_count=0`
- 每个 command step 的 command、output_paths、stop_on_failure 和 external_call_risk 可审计
- `ready_to_execute` 只在 runbook verifier 通过且必需环境存在时为 true
- env-file metadata 必须记录 path/exists/loaded/errors/hygiene，但 required/recommended 检查只能记录 source、value_length、sha256_prefix 和 `secret_redacted=true`
- 含真实条目的 env-file 若权限不是 `0600`，或在工作区内未被 gitignore / 已被 git tracked，dry-run 必须停在 `environment.status=fail`
- process env 必须优先于 env-file；env-file 只补缺失值；执行 JSON 不允许出现 `value` 或 `raw_value` 字段

readiness gate 必须确认：

- readiness output 只记录 env-file path/exists/loaded/errors/hygiene、变量来源、长度和 sha256 前缀，不输出原始 secret
- 含真实条目的 env-file 若权限不是 `0600`，或在工作区内未被 gitignore / 已被 git tracked，readiness 必须返回 fail
- process env 必须优先于 env-file；env-file 只补缺失值
- `GENO_AU_P0A_REQUIRE_DB_CHECK=1` 时，DB gate 使用合并后的 `DATABASE_URL` 做只读 `SELECT 1`，仍不得输出连接串
- preflight/small_batch/full_batch 三个阶段的上游 payload 和 manifest gate 必须按阶段递进，不允许跳过缺失产物

evidence package 必须确认：

- runbook、environment report、runbook execution dry-run、readiness、preflight、small batch、full batch 和对应 manifest 是否存在
- 每个已存在文件的 file sha256、payload hash 或 manifest hash
- 每个 payload/manifest 的 verifier status、ready_for_design_partner 和 blocking reasons
- missing_artifacts、failed_artifacts、blocking_reasons 和 package_payload_hash

package verifier 必须确认：

- package_payload_hash 可复算
- artifacts 至少包含 runbook、environment、runbook_execution、readiness、preflight/small/full JSON 与 manifest
- summary 的 artifact_count、missing_artifacts、failed_artifacts、ready_artifacts、blocking_reasons 可由 artifacts 反推
- `ready_for_design_partner` 与 preflight/small/full JSON 和 manifest 的 ready 状态一致
- package verifier 递归拒绝 `value` / `raw_value`，避免手工拼包时把 secret 塞回证据包

status report 必须确认：

- status_report_hash 可由 `make verify-au-p0a-status` 复算
- runbook verifier、environment report、runbook execution dry-run、同源 env-file preflight/small_batch/full_batch readiness、package verifier 均有机器可读摘要
- completion_percent、design_ready_artifact_percent、remaining_blockers 和 next_action 能回答当前还差多少
- status verifier 递归拒绝 `value` / `raw_value`，避免总控状态报告泄露 env-file、process env 或数据库连接串
- 默认可用于日常进度复盘；需要硬门禁时用 `python3 scripts/verify_au_p0a_status_report.py --require-design-partner-ready`

execution checklist 必须确认：

- `p0a_execution_checklist_hash` 可由 `make verify-au-p0a-execution-checklist` 复算
- setup commands 固定 env template gate、env 模板复制、runbook、env report、environment checklist 和 dry-run 顺序
- execution commands 固定 preflight、preflight manifest、small batch、small manifest、full batch 和 full manifest 的运行/验证顺序
- verification commands 固定 environment、runbook execution、preflight、package 和 status hard gates
- evidence outputs 至少覆盖 runbook、environment report、environment checklist、runbook execution、readiness、preflight、small/full payload、manifest、package 和 status report
- missing_artifacts、failed_artifacts、remaining_blockers、completion_percent 和 design_ready_artifact_percent 能回答当前还差多少
- verifier 递归拒绝 `value` / `raw_value`，避免执行清单泄露 env-file、process env 或数据库连接串
- 该清单证明真实 P0a 执行路径、命令顺序、证据索引和阻塞项可审计，不证明 provider key、数据库、small batch 或 2400-run full batch 已实际完成

## 当前边界

本手册固定真实 AU P0a API-first 执行路径，不代表已经完成真实 provider key 联调、真实 2400 runs、Google spike、真实 ChatGPT 浏览器抽检或生产不可变归档。真实运行后，应保留 gitignored JSON 产物，并把摘要写回 `docs/工程实施审计日志.md`。
