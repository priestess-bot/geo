# AU Customer Handoff Package Manifest

This manifest is generated from the hash-only customer handoff package index.
It records paths, statuses and hashes only; raw answers, citation URLs, assets, secrets and provider payloads are not embedded.

## Status

- Generated at: `2026-06-16T05:48:46Z`
- Package manifest: `ready`
- Customer delivery: `blocked`
- Report export handoff: `blocked`
- Engineering progress: `46.2%`
- Customer readiness: `10.0%`
- Trial customer handoff: `blocked`
- Trial readiness: `87.5%`
- Trial Google coverage: `limited_coverage_appendix_allowed`
- Trial full batch: `deferred_to_formal_launch`
- Structural auditability: `100.0%`
- Missing customer gates: `9`
- Next command: `make au-p0a-env`
- Current clearance request: `p0a_credential_request`
- Current clearance request hash: `9440a97f814c`
- Current completion contract: `ready`
- Current completion contract version: `au_p0a_credential_request_completion_contract_v1`
- Current credential receipt endpoint: `GET /v1/p0a-credential-update-receipt/au`
- Current receipt strict gate: `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_update_receipt.py ${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} --require-complete`

## Customer-Visible Artifacts

| Name | Path | Status | Hash |
| --- | --- | --- | --- |
| handoff_dossier | docs/runtime_preflight/au-handoff-dossier-latest.json | pass | 0164f75ea528 |
| handoff_dossier_markdown | docs/runtime_preflight/au-handoff-dossier-latest.md | pass | e15e7e141884 |
| p0c_report_package | docs/runtime_preflight/au-p0c-report-package-latest.json | pass | 5c0d1cab9131 |

## Source Artifact Index

| Name | Stage | Type | Status | Hash Field | Hash | Required | Customer Visible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| customer_handoff_clearance | handoff | json | pass | customer_handoff_clearance_hash | c0bb1086c471 | yes | no |
| customer_handoff_readiness | handoff | json | pass | customer_handoff_readiness_hash | 0bc15908a851 | yes | no |
| delivery_progress | handoff | json | pass | delivery_progress_hash | b2dbd66d6a40 | yes | no |
| external_dependency_clearance | external_dependency | json | pass | clearance_execution_hash | 463283820c6d | yes | no |
| external_dependency_handoff | external_dependency | json | pass | external_dependency_handoff_hash | 897d28b06708 | yes | no |
| handoff_dossier | handoff | json | pass | handoff_dossier_hash | 0164f75ea528 | yes | yes |
| handoff_dossier_markdown | handoff | markdown | pass | file_sha256 | e15e7e141884 | yes | yes |
| next_work_item | handoff | json | pass | next_work_item_packet_hash | e8bb5afe0229 | yes | no |
| p0a_credential_clearance | p0a | json | pass | p0a_credential_clearance_hash | eb67f3f24b2c | yes | no |
| p0a_credential_update_receipt | p0a | json | pass | p0a_credential_update_receipt_hash | a2ba0b609fb0 | yes | no |
| p0a_evidence_package | p0a | json | pass | package_payload_hash | c0055a29990e | yes | no |
| p0a_real_batch_clearance | p0a | json | pass | p0a_real_batch_clearance_hash | d6ec805af4df | yes | no |
| p0b_google_environment_clearance | p0b_google | json | pass | p0b_google_environment_clearance_hash | 89fc0987c24d | yes | no |
| p0b_google_evidence_package | p0b_google | json | pass | package_payload_hash | 0a994298bbf2 | yes | no |
| p0b_google_manual_backfill_clearance | p0b_google | json | pass | p0b_google_manual_backfill_clearance_hash | adaad9de04ea | yes | no |
| p0b_google_phase_execution_clearance | p0b_google | json | pass | p0b_google_phase_execution_clearance_hash | e36fabef0891 | yes | no |
| p0c_report_package | p0c | json | pass | package_payload_hash | 5c0d1cab9131 | yes | yes |

## Hard Gates

- `make au-customer-handoff-package`
- `make verify-au-customer-handoff-package`
- `make au-handoff-dossier`
- `make verify-au-handoff-dossier`
- `make au-customer-handoff-readiness`
- `make verify-au-customer-handoff-readiness`
- `make au-next-work-item`
- `make verify-au-next-work-item`
- `make au-delivery-progress`
- `make verify-au-delivery-progress`
- `make au-customer-handoff-clearance`
- `make verify-au-customer-handoff-clearance`
- `make au-p0a-credential-update-receipt`
- `make verify-au-p0a-credential-update-receipt`
- `make au-p0a-package`
- `make verify-au-p0a-package`
- `make au-p0b-google-package`
- `make verify-au-p0b-google-package`
- `make au-p0c-report-package`
- `make verify-au-p0c-report-package`
- `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_clearance.py ${GENO_AU_CUSTOMER_HANDOFF_CLEARANCE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-clearance-latest.json} --require-cleared`
- `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_p0a_credential_update_receipt.py ${GENO_AU_P0A_CREDENTIAL_UPDATE_RECEIPT_OUTPUT_PATH:-docs/runtime_preflight/au-p0a-credential-update-receipt-latest.json} --require-complete`
- `PYTHONPATH=packages/geno_core:apps/api python3 scripts/verify_au_customer_handoff_package.py ${GENO_AU_CUSTOMER_HANDOFF_PACKAGE_OUTPUT_PATH:-docs/runtime_preflight/au-customer-handoff-package-latest.json} --require-ready`

## Boundary

- This Markdown manifest is a readable index over the JSON package.
- The JSON package remains the source of truth for machine verification.
- Strict customer delivery still requires `scripts/verify_au_customer_handoff_package.py --require-ready`.
