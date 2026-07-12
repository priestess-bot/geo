# Content v2 gate approvals

These records are the auditable approval source for the implementation gates defined in
`docs/GEO-文案生成系统最终设计方案v2_0.md`.

Rules:

- Keep a gate `pending` until every required conclusion is `approved` and all required evidence hashes are present.
- Use `rejected` for a reviewed gate that must not proceed; use `pending` when review has not finished.
- Never copy evidence hashes from another commit or gate run.
- Product, Engineering, Security, and Delivery must be recorded separately.
- A later code, schema, OpenAPI, prompt-system, or gate-input change invalidates approval unless its hash remains identical.
- Deviations require an owner, expiry date, remediation, and explicit stakeholder acceptance.

Files:

```text
gate-0-baseline.yaml
gate-1-schema-parity.yaml
gate-2-content-core.yaml
gate-3-delivery-customer.yaml
gate-4-publication-connectors.yaml
gate-5-production-pilot.yaml
```
