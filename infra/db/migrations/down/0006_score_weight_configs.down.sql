ALTER TABLE visibility_score_snapshots
  DROP COLUMN IF EXISTS component_weights_snapshot;

DROP TABLE IF EXISTS score_weight_configs;
