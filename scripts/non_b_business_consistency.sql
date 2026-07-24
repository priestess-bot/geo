CREATE TEMP TABLE geo_non_b_consistency_inventory (
    relation_name text PRIMARY KEY
);

CREATE TEMP TABLE geo_non_b_consistency_scopes (
    relation_name text NOT NULL,
    scope_id text NOT NULL,
    row_count bigint NOT NULL,
    rows_sha256 text NOT NULL,
    PRIMARY KEY (relation_name, scope_id)
);

INSERT INTO geo_non_b_consistency_inventory(relation_name)
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND (
      table_name = 'prompt_programs'
      OR table_name LIKE 'prompt_program\_%' ESCAPE '\'
      OR table_name LIKE 'model_gateway\_%' ESCAPE '\'
      OR table_name LIKE 'synthetic_lab\_%' ESCAPE '\'
      OR table_name LIKE 'sampling\_%' ESCAPE '\'
      OR table_name LIKE 'workflow_c\_%' ESCAPE '\'
      OR table_name LIKE 'recommendation\_%' ESCAPE '\'
  )
ORDER BY table_name;

DO $geo_non_b_consistency$
DECLARE
    target record;
    has_project_id boolean;
    statement text;
BEGIN
    FOR target IN
        SELECT relation_name FROM geo_non_b_consistency_inventory ORDER BY relation_name
    LOOP
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = target.relation_name
              AND column_name = 'project_id'
        ) INTO has_project_id;

        IF has_project_id THEN
            statement := format(
                $sql$
                INSERT INTO geo_non_b_consistency_scopes(
                    relation_name, scope_id, row_count, rows_sha256
                )
                SELECT %L, project_id::text, count(*),
                       encode(digest(convert_to(string_agg(
                           encode(digest(convert_to(to_jsonb(source_row)::text, 'UTF8'),
                                         'sha256'), 'hex'),
                           '' ORDER BY encode(digest(convert_to(
                               to_jsonb(source_row)::text, 'UTF8'), 'sha256'), 'hex')
                       ), 'UTF8'), 'sha256'), 'hex')
                FROM %I AS source_row
                GROUP BY project_id
                $sql$,
                target.relation_name,
                target.relation_name
            );
        ELSE
            statement := format(
                $sql$
                INSERT INTO geo_non_b_consistency_scopes(
                    relation_name, scope_id, row_count, rows_sha256
                )
                SELECT %L, '__global__', count(*),
                       encode(digest(convert_to(coalesce(string_agg(
                           encode(digest(convert_to(to_jsonb(source_row)::text, 'UTF8'),
                                         'sha256'), 'hex'),
                           '' ORDER BY encode(digest(convert_to(
                               to_jsonb(source_row)::text, 'UTF8'), 'sha256'), 'hex')
                       ), ''), 'UTF8'), 'sha256'), 'hex')
                FROM %I AS source_row
                $sql$,
                target.relation_name,
                target.relation_name
            );
        END IF;
        EXECUTE statement;
    END LOOP;
END
$geo_non_b_consistency$;

WITH table_rollups AS (
    SELECT inventory.relation_name,
           coalesce(sum(scope.row_count), 0)::bigint AS total_count,
           encode(digest(convert_to(coalesce(string_agg(
               scope.scope_id || ':' || scope.row_count::text || ':' || scope.rows_sha256,
               E'\n' ORDER BY scope.scope_id COLLATE "C"
           ), ''), 'UTF8'), 'sha256'), 'hex') AS aggregate_sha256,
           coalesce(
               jsonb_object_agg(
                   scope.scope_id,
                   jsonb_build_object(
                       'row_count', scope.row_count,
                       'rows_sha256', scope.rows_sha256
                   )
                   ORDER BY scope.scope_id
               ) FILTER (WHERE scope.scope_id IS NOT NULL),
               '{}'::jsonb
           ) AS scopes
    FROM geo_non_b_consistency_inventory AS inventory
    LEFT JOIN geo_non_b_consistency_scopes AS scope
      ON scope.relation_name = inventory.relation_name
    GROUP BY inventory.relation_name
)
SELECT jsonb_build_object(
    'invariant_violations', '{}'::jsonb,
    'migration_revision', (
        SELECT version_num FROM alembic_version ORDER BY version_num DESC LIMIT 1
    ),
    'schema_version', 'geo-non-b-business-consistency-v1',
    'tables', coalesce(
        jsonb_object_agg(
            relation_name,
            jsonb_build_object(
                'aggregate_sha256', aggregate_sha256,
                'scopes', scopes,
                'total_count', total_count
            )
            ORDER BY relation_name
        ),
        '{}'::jsonb
    )
)
FROM table_rollups;
