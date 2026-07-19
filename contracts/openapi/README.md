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

The exporter clears the caller environment and imports only the deployed Internal
and Customer application entrypoints. Generation must not depend on deployment
configuration or include secret values.
Customer validation also rejects internal routes and non-allowlisted writes.
Generated JSON files must not be edited by hand.

These snapshots detect whether a deployed surface changed; matching a freshly
generated snapshot does not by itself prove backward compatibility with a previous
release. The current prototype supports synchronized in-repository clients and an
atomic application/database deployment. Any intentional breaking `/v1` change must
have a migration note and must not be deployed while older API, Web, Worker, Relay,
or out-of-repository clients are still active. External long-lived clients require
an explicit compatibility layer before they can be supported across such a release.
