ALTER TABLE report_exports
  ADD COLUMN IF NOT EXISTS method_disclosure jsonb;
