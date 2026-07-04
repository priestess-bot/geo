# GENO SaaS AU 试点交付 4 日执行计划

版本日期：2026-06-16  
执行窗口：2026-06-16 至 2026-06-19  
适用范围：澳大利亚首发 design partner / trial customer 的技术试点交付，不替代正式客户交付硬门禁。

## 1. 执行口径

本计划把 AU 首发拆成两条互不混淆的放行线：

| 放行线 | 目标 | 是否允许 4 日内交付 | 关键限制 |
| --- | --- | --- | --- |
| 正式客户报告交付 | 完整 P0a/P0b/P0c，可售报告和复测链路 | 否，继续由 `--require-customer-ready`、`--require-ready`、`--require-cleared` 硬门禁控制 | 真实 provider key、P0a preflight/small/full batch、Google env/manual/health/full spike/main scoring 和报告全量交付必须完成 |
| Trial customer handoff | 给试点客户交付可审计、可复盘、可解释的有限试点包 | 是，前提是 8 个 trial gate 全部通过 | Google 允许 `limited_coverage_appendix_allowed`；P0a full batch 不作为 trial 阻塞项，状态固定为 `deferred_to_formal_launch` |

试点交付不是降低正式交付标准，而是新增一个机器可读的有限交付合同：`trial_handoff_version=au_trial_customer_handoff_v1`。该合同必须同时出现在 delivery progress、customer handoff readiness、customer handoff clearance、customer handoff package、FastAPI endpoint 和 Runtime Console。

## 2. Trial Gate 合同

| Gate ID | 判定含义 | 主要证据 | 4 日试点要求 |
| --- | --- | --- | --- |
| `trial_p0a_credentials_ready` | P0a `OPENAI_API_KEY` / `PERPLEXITY_API_KEY` 已完成脱敏回执或清障完成 | `au-p0a-credential-update-receipt-latest.json`、credential fulfillment / clearance | 必须通过 |
| `trial_p0a_preflight_ready` | P0a provider preflight 可复盘，且未被凭证阻塞 | P0a real batch fulfillment / launch status / phase clearance | 必须通过 |
| `trial_p0a_small_batch_ready` | 试点所需小批量 evidence 已可复盘 | P0a real batch fulfillment / launch status / phase clearance | 必须通过；full batch 不阻塞 trial |
| `trial_p0c_report_contract_ready` | P0c 报告合同、method disclosure、traceability contract 可用 | `au-p0c-report-package-latest.json`、launch status | 必须通过 |
| `trial_google_limited_coverage_conclusion_ready` | Google 有 limited coverage 结论或验证失败结论，能进入方法附录 | P0b Google package/status/clearance | 必须通过；不要求进主评分分母 |
| `trial_customer_package_manifest_ready` | 客户包 manifest 结构完整、source artifact 可索引 | `au-customer-handoff-package-latest.json` | 必须通过 |
| `trial_traceability_ready` | 报告到 score/evidence/source/action/audit 可追溯 | P0c package / handoff dossier / traceability contract | 必须通过 |
| `trial_structural_auditability_ready` | 结构化审计度达到 100% | customer handoff readiness / dossier | 必须通过 |

当前本地刷新口径用于制定计划：正式工程进度仍为 `engineering_progress_percent=46.2`，正式客户报告 readiness 仍为 `customer_report_handoff_readiness_percent=10.0`，结构化可审计度为 `100.0`。试点链路的当前缺口集中在 P0a 凭证、P0a preflight 与 P0a small batch；客户包 manifest、P0c 合同、traceability 与结构化审计链路已具备机器可读基础。以 package 视角，manifest 与多数交付索引已 ready，但 `trial_p0a_credentials_ready` 仍会阻止对外标记为 ready。

## 3. 固定产物

4 日内必须形成以下可审计产物：

| 产物 | 路径 / Endpoint | 验收方式 |
| --- | --- | --- |
| 试点 4 日计划 | `docs/GENO-SaaS-AU-试点交付4日计划.md` | 文档包含日期、季度块、交付物、命令、验收和上线效果 |
| Delivery progress | `docs/runtime_preflight/au-delivery-progress-latest.json` / `GET /v1/delivery-progress/au` | `scripts/verify_au_delivery_progress.py` 通过，并含 trial summary |
| Customer handoff readiness | `docs/runtime_preflight/au-customer-handoff-readiness-latest.json` / `GET /v1/customer-handoff-readiness/au` | `scripts/verify_au_customer_handoff_readiness.py` 通过，并含 trial audit |
| Customer handoff clearance | `docs/runtime_preflight/au-customer-handoff-clearance-latest.json` / `GET /v1/customer-handoff-clearance/au` | `scripts/verify_au_customer_handoff_clearance.py` 通过，并对照 delivery progress |
| Customer handoff package | `docs/runtime_preflight/au-customer-handoff-package-latest.json` 与 `.md` / `GET /v1/customer-handoff-package/au` | `scripts/verify_au_customer_handoff_package.py` 通过，并含 trial manifest 摘要 |
| P0b Google 环境行动计划 | `docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json`、`au-p0b-google-environment-clearance-latest.json` | fulfillment / clearance verifier 通过，并含 owner、action item、validation command count |
| Runtime Console | `apps/web/app/page.tsx` | Web 合同测试与 `make web-typecheck` 通过，页面展示 trial handoff 与 P0b action plan |

`docs/runtime_preflight/*` 是 gitignored runtime artifact，用于本地审计复盘；仓库提交只记录生成器、verifier、合同测试、文档和哈希/状态摘要，不提交 secret 原文。

## 4. 逐日执行计划

### 2026-06-16

| 时间块 | 目标 | 交付物 | 验收 / 上线效果 |
| --- | --- | --- | --- |
| Q1 09:00-11:00 | 冻结 trial handoff 技术合同 | `scripts/au_trial_handoff.py`，8 个 gate 常量，Google limited coverage 与 full batch deferred 策略 | 单测能复算 gate order、ready count、blocked gate ids、percent |
| Q2 11:00-13:00 | 接入 delivery progress、readiness、clearance、package 四处 summary | 对应 build / verify 脚本更新，top-level `ready_for_trial_customer_handoff` 与 `trial_handoff_audit` 落盘 | 篡改 trial summary 后 verifier 失败；正式 customer handoff gate 不被放松 |
| Q3 14:00-17:00 | 接入 API 与 Web Console 合同 | FastAPI endpoint 测试、`apps/web/app/page.tsx` 类型和展示字段 | API 合同测试能读取 trial fields；Console 展示 trial readiness、blocked gates、coverage mode、full batch status |
| Q4 17:00-20:00 | 同步计划文档和审计日志 | 本文件、`PROJECT-PLAN.md`、`README.md`、`docs/工程实施审计日志.md` | 文档能说明当前状态、执行命令、审计路径和 secret 边界 |

### 2026-06-17

| 时间块 | 目标 | 交付物 | 验收 / 上线效果 |
| --- | --- | --- | --- |
| Q1 09:00-11:00 | 完成 P0a credential 注入后的脱敏回执 | `.env.au-p0a` 或进程环境只本地注入，刷新 `au-p0a-env`、credential fulfillment、clearance、update receipt | `verify_au_p0a_credential_update_receipt.py --require-complete` 通过；artifact 不含 raw secret |
| Q2 11:00-13:00 | 跑 P0a provider preflight | `docs/runtime_preflight/api-preflight-latest.json`、preflight manifest | `make verify-api-preflight` 通过；preflight evidence 可点回 provider、prompt、city、k |
| Q3 14:00-17:00 | 跑 P0a small batch 或等价 trial sample | 小批量 collection run summary、raw evidence、manifest | small batch gate 可复算；失败时必须形成 blocked artifact 和下一命令 |
| Q4 17:00-20:00 | 刷新 trial handoff 全链路 | delivery progress、readiness、clearance、package 全部重建 | 试点 readiness 应从 62.5% 推进到至少 87.5%；若凭证和 small batch 全过，应达到 100% |

### 2026-06-18

| 时间块 | 目标 | 交付物 | 验收 / 上线效果 |
| --- | --- | --- | --- |
| Q1 09:00-11:00 | 补齐 Google limited coverage 结论 | P0b Google env fulfillment / clearance action plan，manual / browser / third-party 当前状态摘要 | Google 不进主评分分母；方法附录明确 `limited_coverage_appendix_allowed` |
| Q2 11:00-13:00 | 固化 P0c 报告合同和 traceability 合同 | `au-p0c-report-package-latest.json`、report method disclosure、traceability contract | `make verify-au-p0c-report-package` 通过；报告数字能回指 source artifact |
| Q3 14:00-17:00 | 生成试点客户包 manifest 和 Markdown | `au-customer-handoff-package-latest.json`、`.md` | `customer_handoff_package_manifest_ready=true`；Markdown 展示 trial handoff、trial readiness、Google coverage、full batch status |
| Q4 17:00-20:00 | Runtime Console 冒烟 | Console 页面本地启动或静态合同验证，检查 AU Launch / Delivery / Customer Handoff 卡片 | 试点字段可见；无文本溢出和字段缺失；正式 gate 仍显示 blocked |

### 2026-06-19

| 时间块 | 目标 | 交付物 | 验收 / 上线效果 |
| --- | --- | --- | --- |
| Q1 09:00-11:00 | 终态刷新全部 audit artifact | P0a/P0b/P0c、delivery progress、handoff readiness、clearance、package | 所有非 strict structural verifier 通过；strict formal gate 的失败项必须可解释 |
| Q2 11:00-13:00 | 执行回归测试 | Python unit/API/Web 合同测试、`make web-typecheck`、`git diff --check` | 回归通过；失败项必须落审计日志并定位到具体 blocker |
| Q3 14:00-17:00 | 形成试点交付包 | 试点交付摘要、客户包 Markdown、runtime endpoint 清单、blocked / deferred 明细 | 若 8 个 trial gate 全过，可标记 trial handoff ready；否则只允许内部 dry-run |
| Q4 17:00-20:00 | Git 提交与交付复盘 | commit、审计日志、最终进度快照 | 用户可通过仓库、verifier 和 runtime endpoint 复盘每个结论来源 |

## 5. 执行命令清单

常规刷新：

```bash
make au-p0b-google-environment-fulfillment au-p0b-google-environment-clearance
make au-delivery-progress au-customer-handoff-readiness au-customer-handoff-clearance au-customer-handoff-package
```

核心 verifier：

```bash
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_delivery_progress.py docs/runtime_preflight/au-delivery-progress-latest.json
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py docs/runtime_preflight/au-customer-handoff-readiness-latest.json
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py docs/runtime_preflight/au-customer-handoff-clearance-latest.json
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_package.py docs/runtime_preflight/au-customer-handoff-package-latest.json
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_fulfillment.py docs/runtime_preflight/au-p0b-google-environment-fulfillment-latest.json
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0b_google_environment_clearance.py docs/runtime_preflight/au-p0b-google-environment-clearance-latest.json
```

正式硬门禁仍使用以下命令，不因 trial 计划而放松：

```bash
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_readiness.py docs/runtime_preflight/au-customer-handoff-readiness-latest.json --require-customer-ready
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_launch_status.py docs/runtime_preflight/au-launch-status-latest.json --require-ready
PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py docs/runtime_preflight/au-customer-handoff-clearance-latest.json --require-cleared
```

回归测试：

```bash
PYTHONPATH=packages/geno_core:apps/api python3 -m unittest tests.test_au_delivery_progress tests.test_au_customer_handoff_readiness tests.test_au_customer_handoff_clearance tests.test_au_customer_handoff_package tests.test_api_contracts.ApiContractsTest.test_au_delivery_progress_endpoint_returns_current_machine_readable_progress tests.test_api_contracts.ApiContractsTest.test_au_customer_handoff_readiness_endpoint_returns_standalone_readiness_summary tests.test_api_contracts.ApiContractsTest.test_au_customer_handoff_clearance_endpoint_returns_final_handoff_clearance_packet tests.test_api_contracts.ApiContractsTest.test_au_customer_handoff_package_endpoint_returns_delivery_index tests.test_web_console_contracts
make web-typecheck
git diff --check
```

## 6. 审计与溯源要求

1. 任何真实 secret 只能进入 gitignored env file、进程环境或运行时 secret 管理，不写入 git、Markdown、JSON summary 或审计日志。
2. 可提交内容只能包含：字段名、owner、缺失状态、长度、hash 前缀、artifact hash、verifier status、命令、endpoint 和脱敏策略。
3. 每个 trial gate 必须能回指至少一个 source artifact 和一个 verifier。
4. Delivery progress、customer handoff clearance、customer handoff package 的 trial summary 必须可交叉复算，禁止只在 Web 层展示。
5. Google limited coverage 必须明确写入方法附录，不得混入主评分分母。
6. P0a full batch 在 trial 中固定为 deferred，不得把 `trial_full_batch_required=false` 误解释为正式上线无需 full batch。

## 7. 上线效果定义

4 日试点上线的合格状态：

- `ready_for_trial_customer_handoff=true` 出现在 delivery progress、customer handoff clearance、customer handoff package 和 Runtime Console。
- `trial_customer_handoff_readiness_percent=100.0`，8 个 gate 无 blocked id。
- `trial_google_coverage_mode=limited_coverage_appendix_allowed`。
- `trial_full_batch_required=false` 且 `trial_full_batch_status=deferred_to_formal_launch`。
- 正式 `ready_for_customer_report_handoff` 可以仍为 `false`，但所有 formal blockers 必须具备 next command、owner、source artifact 和 strict gate。
- 客户包 Markdown 可说明 trial 范围、Google limited coverage、full batch deferred、证据路径和当前限制。

若任一 trial gate 未通过，2026-06-19 只能交付内部 dry-run 包，不对外标记 trial ready。
