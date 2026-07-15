# GEO database baseline

Alembic is the only migration entry point for the new GEO schema. The legacy
`infra/db/migrations` and `infra/db/schema-v2` trees remain read-only inputs
during remediation; they are not part of this revision graph.

Set `GEO_DATABASE_URL` to a PostgreSQL psycopg URL and run:

```bash
uv run alembic upgrade head
```

The baseline intentionally targets a fresh database. Existing development test
data is not stamped or upgraded into this schema.
