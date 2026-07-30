DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM browser_egress_tests) THEN
        RAISE EXCEPTION 'cannot downgrade: Browser Egress test evidence exists'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

DROP TRIGGER browser_egress_test_status_reconcile ON durable_jobs;
DROP FUNCTION geo_reconcile_browser_egress_test_status();
DROP FUNCTION geo_enqueue_browser_egress_test(uuid, uuid, uuid, uuid, timestamptz);
DROP TABLE browser_egress_test_specs;
DROP TABLE browser_egress_tests;
