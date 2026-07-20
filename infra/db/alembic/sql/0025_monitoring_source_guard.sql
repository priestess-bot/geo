CREATE FUNCTION geo_assert_monitoring_question_sources_current() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.question_set_id IS NULL AND NEW.question_set_id IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM knowledge_question_set_items AS item
           WHERE item.question_set_id = NEW.question_set_id
             AND item.project_id = NEW.project_id
             AND item.campaign_id = NEW.campaign_id
             AND NOT geo_question_candidate_sources_current(
                 item.question_candidate_id
             )
       ) THEN
        RAISE EXCEPTION 'Monitoring Protocol cannot bind a QuestionSet with stale Knowledge sources'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER monitoring_protocol_question_sources_current_guard
BEFORE UPDATE OF question_set_id ON monitoring_protocols
FOR EACH ROW EXECUTE FUNCTION geo_assert_monitoring_question_sources_current();

REVOKE ALL ON FUNCTION geo_assert_monitoring_question_sources_current()
FROM PUBLIC, geo_app, geo_worker, geo_readonly;
GRANT EXECUTE ON FUNCTION geo_assert_monitoring_question_sources_current()
TO geo_app;
