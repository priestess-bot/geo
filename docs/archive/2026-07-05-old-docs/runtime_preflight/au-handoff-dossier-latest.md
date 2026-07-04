# AU 客户交付总包

- 生成时间：2026-06-15T00:21:33Z
- Dossier 状态：pass
- 客户报告交付准入：blocked
- 当前姿态：blocked_external_dependencies
- 下一步：configure_required_environment
- 下一 work item：p0a_environment
- Launch status hash：7b91bdabc48a52d71dc0c1e5e880cd1d1d29f9d86bab3141aa3cdcd9959d66ce
- Remediation plan hash：670baaab9a66a21618e6466aac53d3aaa4295c18c2e9ccf4564239c866bd16f9
- P0a environment checklist hash：49448bcfe90beeb01ceff9a2b4110ae1b5c6e606c7b97d8ff252f5ffe132a956
- P0a execution checklist hash：1d6a95bedf013a33e120f51f1376bff9b2535a47997e508d79fbfbc2f30a0820
- P0b Google execution checklist hash：ef6357fc9dca88ff40fbaf2c5dcef5aaf07481d472ade1a572254eab05b953b9

## 客户交付 Readiness Audit

- Audit version：au_customer_handoff_readiness_audit_v1
- 客户报告交付 readiness：10.0%
- 结构化可审计度：100.0%
- 客户交付 gates：1/10 ready
- Blocked customer gates：p0a_credentials_configured, p0a_real_batches_ready, p0a_design_partner_data_ready, p0b_google_environment_ready, p0b_google_manual_backfill_ready, p0b_google_phase_execution_ready, p0b_google_main_scoring_ready, external_dependencies_clear, customer_report_handoff_gate
- 外部依赖 blocker：25
- Readiness statement：blocked_external_dependencies

## 阶段门禁

| 阶段 | 状态 | Ready | 下一步 | Blockers |
| --- | --- | --- | --- | ---: |
| P0a Design Partner Data | fail | no | configure_required_environment | 18 |
| P0b Google Spike | fail | no | populate_google_playwright_smoke_environment | 7 |
| P0c Customer Report Contract | pass | yes | ready_for_p0c_customer_report_handoff | 0 |

## Blocker 覆盖

- 总 blocker 数：25
- 已映射 blocker 数：25
- 未映射 blocker 数：0
- 外部依赖 blocker 数：25
- Work item 数：8

## 下一 Work Item

- ID：p0a_environment
- 阶段：P0a
- 标题：Configure AU P0a provider keys and runtime database
- 依赖类型：provider_keys_and_database
- 覆盖 blocker 数：8

### 执行命令

- `make verify-au-p0a-env-template`
- `make au-p0a-env-bootstrap`
- `make verify-au-p0a-env-bootstrap`
- `make au-p0a-runbook`
- `make au-p0a-env`
- `make verify-au-p0a-env`
- `make au-p0a-environment-checklist`
- `make verify-au-p0a-environment-checklist`
- `make au-p0a-readiness`

### 验证命令

- `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_env_report.py ${GENO_AU_P0A_ENV_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-env-latest.json} --require-ready-environment`
- `make au-p0a-status`
- `make verify-au-p0a-status`

## P0a 环境清单

- 状态：fail
- Ready：no
- 下一步：populate_required_environment
- 必填变量：1/3
- 缺失必填：PERPLEXITY_API_KEY, OPENAI_API_KEY
- 缺失推荐：无
- Env-file hygiene：ready（errors: 0, warnings: 0）
- Env-file hygiene path：.env.au-p0a
- Runbook verifier：pass
- Environment verifier：pass

## P0a 执行清单

- 状态：fail
- Ready：no
- Design partner ready：no
- 下一步：configure_required_environment
- Small batch planned runs：30
- Full batch planned runs：2400
- 缺失 artifact：small_batch_json, full_batch_json, small_batch_manifest, full_batch_manifest
- Remaining blockers：18
- Credential handoff：blocked（missing: 2, redacted: yes）
- Credential missing：PERPLEXITY_API_KEY, OPENAI_API_KEY
- Credential target env file：.env.au-p0a
- Real batch phase handoff：blocked（next: preflight, ready phases: 0, blocked phases: 3, planned runs: 2436）
- Real batch phase order：preflight, small_batch, full_batch
- Status verifier：pass

## P0b Google 执行清单

- 状态：fail
- Ready：no
- Google 主评分准入：no
- 下一步：populate_google_playwright_smoke_environment
- Planned runs：240
- 缺失 smoke env：GOOGLE_PLAYWRIGHT_ENABLED
- 缺失 full-run env：DATABASE_URL, MANUAL_BACKFILL_PATH
- 缺失 selector group：google_aio_answer_selector, google_aio_prompt_selector
- Env-file hygiene：ready（errors: 0, warnings: 0）
- Env-file hygiene path：.env.au-p0b-google
- Environment handoff：blocked（missing: 5, redacted: yes）
- Environment handoff missing：smoke_env:GOOGLE_PLAYWRIGHT_ENABLED, full_run_env:DATABASE_URL, full_run_env:MANUAL_BACKFILL_PATH, selector_group:google_aio_answer_selector, selector_group:google_aio_prompt_selector
- Environment handoff target env file：.env.au-p0b-google
- Manual backfill handoff：blocked（rows: 0/120, prompt-city: 0/60, missing: 1, redacted: yes）
- Manual backfill missing：manual_backfill:file_missing
- Manual backfill template：docs/runtime_preflight/au-p0b-google-manual-backfill-template.jsonl
- Manual backfill verification：docs/runtime_preflight/au-p0b-google-manual-backfill-verification-latest.json
- Google spike phase handoff：blocked（next: environment, ready phases: 0, blocked phases: 6, full spike runs: 240）
- Google spike phase order：environment, browser_smoke, manual_backfill, health_check, full_spike, main_scoring
- Remaining blockers：7
- Status verifier：pass
- Package verifier：pass

## Runtime 复盘入口

- 项目生命周期：`GET /v1/projects/runtime/lifecycle-events?project_id={project_id}`
- 项目生命周期 CSV：`GET /v1/projects/runtime/lifecycle-events/export.csv?project_id={project_id}`
- 项目审计轨道：`GET /v1/audit-events/runtime?project_id={project_id}`
- 项目审计 CSV：`GET /v1/audit-events/runtime/export.csv?project_id={project_id}`
- 外部依赖交接：`GET /v1/external-dependency-handoff/au`
- 外部依赖清零 dry-run：`GET /v1/external-dependency-clearance/au`

## 证据来源

| 名称 | 存在 | sha256 | 路径 |
| --- | --- | --- | --- |
| launch_status | yes | 06b2c28c20bce83b12a6292eadb3858b17acd285afcaebc21166d0fb5a24d149 | `docs/runtime_preflight/au-launch-status-latest.json` |
| remediation_plan | yes | 89baf749a63065e4563ccf69d045796ba06dd72e79c7a9359a8831b2e6203377 | `docs/runtime_preflight/au-launch-remediation-plan-latest.json` |
| p0a_environment_checklist | yes | c30add0c54513d6d85cfdbf39ca121e84cc32541a3422c8ae5b0263628ce247b | `docs/runtime_preflight/au-p0a-environment-checklist-latest.json` |
| p0a_execution_checklist | yes | 584fca1c5df2b1fe972c54fa655d2df19e2c5b07657c5968d280f9104e447a60 | `docs/runtime_preflight/au-p0a-execution-checklist-latest.json` |
| p0b_google_execution_checklist | yes | fc51f58feb9536a80a8b15cd4f580573718c7a5f473c801658b69249d52b147c | `docs/runtime_preflight/au-p0b-google-execution-checklist-latest.json` |
| p0a_status | yes | 3417f9133a70c199e362658826b2d3606274edb3e40cfd5e514f092bb8ff803b | `docs/runtime_preflight/au-p0a-status-latest.json` |
| p0b_google_status | yes | f585d143e39d56b2c6ff7491f703fe5c0c17f5175eb1c6576ca394415e4be3a8 | `docs/runtime_preflight/au-p0b-google-spike-status-latest.json` |
| p0b_google_package | yes | 6525ef6b10965ebebf07773379efb45ccf13674460922e3757c7ddff6b991dc3 | `docs/runtime_preflight/au-p0b-google-evidence-package-latest.json` |
| p0c_report_package | yes | b9dfe7549c304f1734dca06e707b5ac978ba3c3a001f7778f5064e5336e4c31d | `docs/runtime_preflight/au-p0c-report-package-latest.json` |

## 当前边界

- 本总包证明当前 AU launch 状态、清障计划和本地证据索引可复算。
- 本总包不代表真实 P0a provider 批次、P0b Google 240-run 或生产发布门禁已经完成。
- 真实客户报告交付硬门禁仍以 `scripts/verify_au_launch_status.py --require-ready` 为准。
