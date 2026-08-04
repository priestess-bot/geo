ALTER TABLE synthetic_lab_command_receipts
DROP CONSTRAINT synthetic_lab_command_receipts_operation_check;

ALTER TABLE synthetic_lab_command_receipts
ADD CONSTRAINT synthetic_lab_command_receipts_operation_check
CHECK (operation IN (
    'create_authorization', 'reassess_authorization', 'decide_authorization',
    'expire_authorization', 'revoke_authorization', 'admit_collection',
    'claim_collection', 'create_style_source', 'create_style_profile',
    'create_channel_style', 'create_review_suite', 'create_review_case',
    'import_samples', 'freeze_profile', 'submit_profile', 'freeze_suite',
    'enqueue_generation', 'enqueue_revision', 'enqueue_corpus',
    'enqueue_experiment', 'claim_job', 'enqueue_execution', 'cancel_job',
    'finalize_result', 'finalize_experiment'
));
