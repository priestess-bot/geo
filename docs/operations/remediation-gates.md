# GEO remediation gates

These commands are delivery gates. They fail on a missing required environment value, zero
collected tests, or a skipped required test. Commands print configuration field names and stable
error codes; they do not print Secret values.

## Pull request gates

`make test-integration-required` requires every PostgreSQL identity, the acceptance isolation
marker, and `GEO_F019_TEST_MINIO_ENDPOINT`. It upgrades the selected disposable database and runs
the complete integration selection with skip and collection accounting.

`make test-browser-chromium` runs the Admin and Customer portals as two Chromium desktop suites.
The JSON result auditor rejects zero collection, skipped tests, and unexpected failures.

`make geo-acceptance-inline` requires these environment variables:

```text
GEO_ACCEPTANCE_APP_DATABASE_URL
GEO_ACCEPTANCE_WORKER_DATABASE_URL
GEO_ACCEPTANCE_ADMIN_DATABASE_URL
GEO_ACCEPTANCE_ISOLATION_MARKER
```

The database must carry the same database-scoped isolation marker and use distinct Admin, App,
and Worker principals. The target uses controlled adapters and a process-local artifact store. Its
report must say `execution_mode=inline_isolated` and must say that it did not validate production
Worker/Relay topology or perform external publication.

`make test-infra-contracts` validates Compose, preflight, healthcheck, network, and Secret-file
contracts without contacting an external provider.

The required integration selection also runs `F001-INT-01` against one local HTTP server. Real
requests cover OIDC discovery/JWKS and RS256 token verification, Knowledge URL fetch, an
OpenAI-compatible model request, and publication HTML inspection. The local fixture is test-only;
it is not staging evidence.

## Production-equivalent runtime gate

`make test-infra-runtime` requires a working Docker daemon. It creates a unique Compose project and
disposable PostgreSQL volume, migrates it, provisions separate App/Worker roles, and then runs the
real readiness dependency failure matrix, Worker heartbeat/stale and queue-stall classifications,
and an isolated backend/egress Compose network test. Teardown removes containers and volumes even
after a failure. It never uses the development or staging Compose project.

The same target starts a disposable Compose healthcheck service, observes Docker report `healthy`,
forces its probe to fail until Docker reports `unhealthy`, then restores it and observes `healthy`
again. This is runtime state evidence, not a YAML string assertion.

## External staging smoke

`make geo-staging-smoke` is never part of an ordinary pull request. It refuses before any network
request unless both are set:

```text
GEO_RUN_STAGING_SMOKE=1
GEO_CONFIRM_STAGING_PAID_MODEL_CALL=1
```

It also requires:

```text
GEO_STAGING_OIDC_DISCOVERY_URL
GEO_STAGING_OIDC_ISSUER
GEO_STAGING_OIDC_AUDIENCE
GEO_STAGING_OIDC_TOKEN_FILE
GEO_STAGING_KNOWLEDGE_URL
GEO_STAGING_PUBLICATION_URL
GEO_STAGING_PUBLICATION_EXPECTED_TEXT
GEO_DEEPSEEK_API_KEY_FILE
```

The token and model key must be regular, non-empty files readable only by their owner. The smoke
validates the discovery issuer, JWKS and token signature, fetches one real Knowledge URL through the
product fetcher, permits exactly one paid model gateway call, and verifies one public HTTPS
publication URL against expected visible text. It writes separate `staging_external` evidence to
`artifacts/geo-staging-smoke/result.json` by default. The report contains hashes and counts, not
tokens, API keys, fetched bodies, or model output.
