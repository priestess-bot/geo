# AU P0a 真实批次运行手册

本文档描述真实 Perplexity/OpenAI key 到位后，从最小 preflight 到完整 AU P0a 批次的执行顺序、产物命名和停止条件。机器可读版本由 `make au-p0a-runbook` 生成，默认写入 gitignored 的 `docs/runtime_preflight/au-p0a-runbook-latest.json`。

## 运行原则

- 先跑最小 preflight，再跑 small batch，最后跑 full batch。
- 每一步都必须先生成 JSON，再 verify，再 manifest。
- “可审计”不等于“可进入 design partner”；进入下一阶段必须通过 `--require-design-partner-ready`。
- live 运行产物位于 `docs/runtime_preflight/*.json`，默认不提交，避免把 provider 状态、错误上下文或潜在敏感配置写入仓库。

## 命令顺序

1. 生成机器可读 runbook：

```bash
make au-p0a-runbook
```

2. 准备环境：

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

3. 最小 provider preflight：

```bash
make api-preflight
make verify-api-preflight
make preflight-manifest
PYTHONPATH=packages/geno_core:apps/api \
python3 scripts/verify_preflight_payload.py \
  docs/runtime_preflight/api-preflight-latest.json \
  --require-design-partner-ready
```

4. 小批次真实采集（默认 5 prompts x Sydney x k=3 x 2 platforms = 30 runs）：

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
```

5. 完整 AU P0a 批次（默认 100 prompts x 4 geo x k=3 x 2 platforms = 2400 runs）：

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
```

## 停止条件

- provider health 不是 `ready`：停止，先修 key、collector 配置或 provider 可用性。
- `P0ACollectionReadinessGate` 未通过：停止，不进入下一阶段。
- `--require-no-collection-failures` 返回非零：停止，先复盘失败样本和重试/限流策略。
- manifest verifier `status=fail`：停止，先修 payload 完整性、必备字段或 gate 状态。
- `ready_for_design_partner=false`：停止，不进入 design partner 或 full batch。

## 产物清单

默认产物路径：

- `docs/runtime_preflight/api-preflight-latest.json`
- `docs/runtime_preflight/api-preflight-manifest-latest.json`
- `docs/runtime_preflight/au-p0a-runbook-latest.json`
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

## 当前边界

本手册固定真实 AU P0a API-first 执行路径，不代表已经完成真实 provider key 联调、真实 2400 runs、Google spike、真实 ChatGPT 浏览器抽检或生产不可变归档。真实运行后，应保留 gitignored JSON 产物，并把摘要写回 `docs/工程实施审计日志.md`。
