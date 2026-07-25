# Pack 01: semantic metric durable vertical

Budget: 12h agent time. Status: `LOCAL_COMPLETE / BLOCKED_EXTERNAL`.

| ID | Timebox | Concrete output | Validation | Status |
|---|---:|---|---|---|
| P01-01 | 45m | Execution index, contract map and non-B boundary test | Documentation/architecture tests | LOCAL_COMPLETE |
| P01-02 | 2h | Metric Protocol Version and Analysis Input Manifest migrations with maker-checker, RLS and controlled RPC | Migration unit and isolated PostgreSQL tests | LOCAL_COMPLETE |
| P01-03 | 90m | Project-scoped protocol/manifest repositories and selector resolver | Unit and repository integration tests | LOCAL_COMPLETE |
| P01-04 | 2h | Worker-only materialization of Provider/manual answer artifacts with hash checks | Reader boundary and artifact tests | LOCAL_COMPLETE |
| P01-05 | 2h | Backward-compatible semantic Job spec v2 and atomic producer | Decoder, admission, replay and tamper tests | LOCAL_COMPLETE |
| P01-06 | 2h | Worker v2 reconstructs input, applies rule/judge/arbiter and writes fenced snapshot | Worker and persistence tests | LOCAL_COMPLETE |
| P01-07 | 90m | Protocol lifecycle and async semantic-job Internal API; old sync route deprecated | OpenAPI and route tests | LOCAL_COMPLETE |
| P01-08 | 90m | PostgreSQL/MinIO/Valkey Suite-to-Snapshot vertical test | Isolated integration test | LOCAL_COMPLETE |
| P01-09 | 45m | Quality run, roadmap/evidence update | Ruff, MyPy, pytest and evidence verifier | LOCAL_COMPLETE |

Acceptance mapping: `C-CONTRACT-01`, `C-CONTRACT-04`, `M4-METRIC-01`, `STAT-VERSION-AC-01`. Board B and live egress/browser evidence are explicitly not required by this pack.

Stop condition: an approved protocol and completed Sampling Run can be selected through a secret-free request, enqueue exactly one immutable Job, materialize governed answers only in the Worker, persist under a valid lease/fence and return the projection without exposing raw text.

## Evidence

- `0073_wfc_metric_protocols`, `0074_wfc_semantic_job_v2` and `0075_wfc_manual_attempt_scope` provide the protocol/manifest, atomic v2 admission and correctly scoped manual/Provider claim contracts. The vertical test executes `head -> 0074 -> head` before use.
- `tests/integration/test_workflow_c_semantic_vertical_postgres.py` uses isolated PostgreSQL roles, a temporary real MinIO server and a temporary real Valkey server. Three independently approved encrypted manual artifacts become three Observations, one completed Run, one immutable semantic manifest and one fenced snapshot. The database outbox relay publishes all four wakeups into Valkey and the test consumes the semantic wakeup by exact Job/Project identity.
- The same test asserts a denominator and valid count of three, immutable projection hash equality, outbox acknowledgement, and absence of answer text, email and token markers from both Job spec and input manifest.
- Targeted non-integration verification: `70 passed in 30.33s` across API, repository, materializer, worker, outbox and all three migration contracts.
- Targeted isolated PostgreSQL verification: `6 passed in 58.60s` across Metric Protocol, semantic admission, manual evidence, the PostgreSQL/MinIO/Valkey vertical and Provider execution-input regression.
- Ruff passed for the Pack 1 production/test surface. Mypy with the repository's `--follow-imports=skip` policy passed for all 11 Pack 1 production modules.

This evidence completes the local implementation pack only. It does not satisfy the roadmap's live Provider, consumer-surface, independent-verifier or final evidence-manifest gates.
