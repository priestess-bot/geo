CREATE TABLE runtime_service_heartbeats (
    service_type text NOT NULL CHECK (service_type IN ('task_worker', 'outbox_relay')),
    container_id text NOT NULL CHECK (
        btrim(container_id) <> '' AND octet_length(container_id) <= 200
    ),
    instance_id text NOT NULL CHECK (
        btrim(instance_id) <> '' AND octet_length(instance_id) <= 240
    ),
    release_version text NOT NULL CHECK (
        btrim(release_version) <> '' AND octet_length(release_version) <= 200
    ),
    status text NOT NULL CHECK (status IN ('starting', 'ready', 'stopping', 'failed')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (service_type, instance_id)
);

CREATE INDEX runtime_service_heartbeats_container_last_idx
ON runtime_service_heartbeats (service_type, container_id, last_heartbeat_at DESC);

CREATE INDEX durable_jobs_runtime_terminal_idx
ON durable_jobs (status, (COALESCE(completed_at, updated_at)) DESC, id)
WHERE status IN ('failed', 'dead_lettered');

COMMENT ON TABLE runtime_service_heartbeats IS
    'Process-level operational evidence. It contains no tenant payload, job error, or credential.';

ALTER TABLE runtime_service_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE runtime_service_heartbeats FORCE ROW LEVEL SECURITY;

CREATE FUNCTION geo_worker_record_runtime_heartbeat(
    p_service_type text,
    p_container_id text,
    p_instance_id text,
    p_release_version text,
    p_status text
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_service_type IS NULL
       OR p_service_type NOT IN ('task_worker', 'outbox_relay')
       OR btrim(COALESCE(p_container_id, '')) = ''
       OR octet_length(p_container_id) > 200
       OR btrim(COALESCE(p_instance_id, '')) = ''
       OR octet_length(p_instance_id) > 240
       OR btrim(COALESCE(p_release_version, '')) = ''
       OR octet_length(p_release_version) > 200
       OR p_status IS NULL
       OR p_status NOT IN ('starting', 'ready', 'stopping', 'failed') THEN
        RAISE EXCEPTION 'invalid runtime heartbeat input' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.runtime_service_heartbeats (
        service_type, container_id, instance_id, release_version, status
    ) VALUES (
        p_service_type, p_container_id, p_instance_id, p_release_version, p_status
    )
    ON CONFLICT (service_type, instance_id) DO UPDATE
    SET container_id = EXCLUDED.container_id,
        release_version = EXCLUDED.release_version,
        status = EXCLUDED.status,
        last_heartbeat_at = clock_timestamp();
END;
$$;

CREATE FUNCTION geo_worker_runtime_findings(
    p_service_type text,
    p_container_id text,
    p_expected_instances integer,
    p_heartbeat_stale_seconds integer,
    p_queued_stale_seconds integer,
    p_running_grace_seconds integer,
    p_outbox_stale_seconds integer,
    p_failure_window_seconds integer
) RETURNS TABLE (
    finding_code text,
    finding_category text,
    severity text,
    project_id uuid,
    job_id uuid,
    age_seconds bigint
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = off
AS $$
BEGIN
    IF p_service_type IS NULL
       OR p_service_type NOT IN ('task_worker', 'outbox_relay')
       OR btrim(COALESCE(p_container_id, '')) = ''
       OR octet_length(p_container_id) > 200
       OR p_expected_instances IS NULL
       OR p_expected_instances NOT BETWEEN 1 AND 100
       OR p_heartbeat_stale_seconds IS NULL
       OR p_heartbeat_stale_seconds NOT BETWEEN 1 AND 3600
       OR p_queued_stale_seconds IS NULL
       OR p_queued_stale_seconds NOT BETWEEN 1 AND 604800
       OR p_running_grace_seconds IS NULL
       OR p_running_grace_seconds NOT BETWEEN 0 AND 86400
       OR p_outbox_stale_seconds IS NULL
       OR p_outbox_stale_seconds NOT BETWEEN 1 AND 604800
       OR p_failure_window_seconds IS NULL
       OR p_failure_window_seconds NOT BETWEEN 1 AND 2592000 THEN
        RAISE EXCEPTION 'invalid runtime finding thresholds' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH ranked_heartbeats AS (
        SELECT
            heartbeat.status,
            heartbeat.last_heartbeat_at,
            row_number() OVER (
                ORDER BY heartbeat.last_heartbeat_at DESC, heartbeat.instance_id DESC
            ) AS freshness_rank
        FROM public.runtime_service_heartbeats AS heartbeat
        WHERE heartbeat.service_type = p_service_type
          AND heartbeat.container_id = p_container_id
    ),
    selected_heartbeats AS (
        SELECT ranked.status, ranked.last_heartbeat_at
        FROM ranked_heartbeats AS ranked
        WHERE ranked.freshness_rank <= p_expected_instances
    ),
    heartbeat_findings AS (
        SELECT
            CASE
                WHEN selected.status <> 'ready' THEN 'runtime_heartbeat_not_ready'
                ELSE 'runtime_heartbeat_stale'
            END::text AS finding_code,
            'runtime_heartbeat'::text AS finding_category,
            'error'::text AS severity,
            NULL::uuid AS project_id,
            NULL::uuid AS job_id,
            GREATEST(
                0,
                floor(extract(epoch FROM clock_timestamp() - selected.last_heartbeat_at))
            )::bigint AS age_seconds
        FROM selected_heartbeats AS selected
        WHERE selected.status <> 'ready'
           OR selected.last_heartbeat_at
              <= clock_timestamp() - make_interval(secs => p_heartbeat_stale_seconds)

        UNION ALL

        SELECT
            'runtime_heartbeat_missing',
            'runtime_heartbeat',
            'error',
            NULL::uuid,
            NULL::uuid,
            NULL::bigint
        FROM (SELECT count(*) AS actual_count FROM selected_heartbeats) AS actual
        WHERE actual.actual_count < p_expected_instances
    ),
    findings AS (
        SELECT heartbeat.* FROM heartbeat_findings AS heartbeat

        UNION ALL

        SELECT
            CASE job.status
                WHEN 'queued' THEN 'durable_job_queued_stalled'
                ELSE 'durable_job_retry_stalled'
            END,
            job.status,
            'error',
            job.project_id,
            job.id,
            GREATEST(0, floor(extract(epoch FROM clock_timestamp() - job.updated_at)))::bigint
        FROM public.durable_jobs AS job
        WHERE job.status IN ('queued', 'retry_wait')
          AND job.next_run_at <= clock_timestamp()
          AND job.updated_at
              <= clock_timestamp() - make_interval(secs => p_queued_stale_seconds)

        UNION ALL

        SELECT
            CASE
                WHEN job.status = 'running'
                     AND job.lease_expires_at
                         <= clock_timestamp() - make_interval(secs => p_running_grace_seconds)
                    THEN 'durable_job_running_recovery_overdue'
                WHEN job.status = 'finalizing'
                     AND job.lease_expires_at
                         <= clock_timestamp() - make_interval(secs => p_running_grace_seconds)
                    THEN 'durable_job_finalizing_recovery_overdue'
                WHEN job.status = 'running' THEN 'durable_job_running_lease_expired'
                ELSE 'durable_job_finalizing_lease_expired'
            END,
            job.status,
            CASE
                WHEN job.lease_expires_at
                     <= clock_timestamp() - make_interval(secs => p_running_grace_seconds)
                    THEN 'error'
                ELSE 'warning'
            END,
            job.project_id,
            job.id,
            GREATEST(
                0,
                floor(extract(epoch FROM clock_timestamp() - job.lease_expires_at))
            )::bigint
        FROM public.durable_jobs AS job
        WHERE job.status IN ('running', 'finalizing')
          AND job.lease_expires_at <= clock_timestamp()

        UNION ALL

        SELECT
            'broker_outbox_delivery_stalled',
            'outbox',
            'error',
            outbox.project_id,
            outbox.job_id,
            GREATEST(
                0,
                floor(extract(epoch FROM clock_timestamp() - outbox.created_at))
            )::bigint
        FROM public.broker_outbox AS outbox
        WHERE outbox.published_at IS NULL
          AND outbox.available_at <= clock_timestamp()
          AND outbox.created_at
              <= clock_timestamp() - make_interval(secs => p_outbox_stale_seconds)

        UNION ALL

        SELECT
            CASE job.status
                WHEN 'dead_lettered' THEN 'durable_job_dead_lettered'
                ELSE 'durable_job_terminal_failed'
            END,
            CASE job.status
                WHEN 'dead_lettered' THEN 'dead_letter'
                ELSE 'terminal_failure'
            END,
            'error',
            job.project_id,
            job.id,
            GREATEST(
                0,
                floor(extract(
                    epoch FROM clock_timestamp() - COALESCE(job.completed_at, job.updated_at)
                ))
            )::bigint
        FROM public.durable_jobs AS job
        WHERE job.status IN ('failed', 'dead_lettered')
          AND COALESCE(job.completed_at, job.updated_at)
              >= clock_timestamp() - make_interval(secs => p_failure_window_seconds)
    )
    SELECT
        item.finding_code,
        item.finding_category,
        item.severity,
        item.project_id,
        item.job_id,
        item.age_seconds
    FROM findings AS item
    ORDER BY
        CASE item.finding_category WHEN 'runtime_heartbeat' THEN 0 ELSE 1 END,
        CASE item.severity WHEN 'error' THEN 0 ELSE 1 END,
        item.finding_code,
        item.project_id NULLS FIRST,
        item.job_id NULLS FIRST
    LIMIT 500;
END;
$$;

REVOKE ALL ON TABLE runtime_service_heartbeats
FROM PUBLIC, geo_app, geo_worker, geo_readonly;

REVOKE ALL ON FUNCTION geo_worker_record_runtime_heartbeat(text, text, text, text, text)
FROM PUBLIC, geo_app, geo_readonly;
REVOKE ALL ON FUNCTION geo_worker_runtime_findings(
    text, text, integer, integer, integer, integer, integer, integer
) FROM PUBLIC, geo_app, geo_readonly;

GRANT EXECUTE ON FUNCTION geo_worker_record_runtime_heartbeat(text, text, text, text, text)
TO geo_worker;
GRANT EXECUTE ON FUNCTION geo_worker_runtime_findings(
    text, text, integer, integer, integer, integer, integer, integer
) TO geo_worker;
