# OpenAPI contracts

The current stable contracts are generated independently from the two deployed
ASGI entrypoints:

- `stable/internal.openapi.json` from `geo_api.internal_app:app`;
- `stable/customer.openapi.json` from `geo_api.customer_app:app`;
- `stable/manifest.json` pins both SHA-256 digests and structural counts.

Update all stable generated files after an intentional API contract change:

```bash
make openapi-snapshots
```

Verify that the checked-in files match the current application:

```bash
make openapi-contracts
```

The exporter clears the caller environment and never imports `geo_api.main`.
Generation must not depend on deployment configuration or include secret values.
Customer validation also rejects internal routes and non-allowlisted writes.
Generated JSON files must not be edited by hand.

The root `geo-api.openapi.json` and `manifest.json` are retained only as a
pre-remediation legacy reference. They are not the stable deployment contracts.
