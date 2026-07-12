# OpenAPI contract

`geno-api.openapi.json` is the canonical FastAPI contract shared by Admin Web
and Customer Web. `manifest.json` pins its SHA-256 digest and structural counts.

Update both generated files after an intentional API contract change:

```bash
make openapi-snapshot
```

Verify that the checked-in files match the current application:

```bash
make openapi-contracts
```

The exporter clears the caller environment before importing the API. Snapshot
generation must not depend on deployment configuration or include secret values.
Generated JSON files must not be edited by hand.
