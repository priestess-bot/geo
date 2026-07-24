# Workflow C Statistical Method Contract v1

This contract freezes how a comparison family is computed and replayed. A method
change creates a new protocol version and never rewrites an existing result.

## Paired bootstrap

- Method ID: `paired-bootstrap-percentile-v1`.
- Unit: the server-resolved pair with the same frozen question, repetition,
  stratum, capture method, baseline version and candidate version.
- Seed: SHA-256 over protocol hash, QuestionSet hash, baseline and candidate
  versions, metric method version and comparison ID.
- The raw interval uses the family alpha frozen before execution.
- The two-sided empirical p-value uses add-one smoothing and is rounded to 12
  decimal places with `ROUND_HALF_UP`.

## Holm family correction

- Method ID: `holm-v1`.
- Order: ascending raw p-value, then comparison ID as the deterministic tie
  breaker.
- Adjusted p-values use the monotone step-down definition
  `max(previous, remaining * raw_p)`, capped at one.
- Rejection stops after the first comparison whose raw p-value is above its
  rank-specific `family_alpha / remaining` threshold.

## Simultaneous practical-effect interval

- Method ID: `paired-bootstrap-percentile-bonferroni-family-v1`.
- Every member of a family is re-bootstrapped with the same frozen pairs and
  seed at `family_alpha / family_size`. The alpha does not depend on observed
  p-value order or Holm rank, so reordering a family cannot narrow a member's
  decision interval. Bonferroni's union bound gives at least `1-family_alpha`
  simultaneous coverage without assumptions about dependence between metrics.
- This simultaneous interval, not the Holm zero-null rejection flag, drives
  win, loss, equivalence and inconclusive decisions against the frozen
  practical threshold. Sample and completion gates take precedence.
- Equivalence uses only the protocol's frozen `a_priori_design_power` and
  `power_method_version=a-priori-design-power-v1`; v1 does not accept or
  compute post-hoc achieved power. The simultaneous interval must also satisfy
  the frozen precision limit.
- Result lineage retains raw/adjusted p-values, Holm rank, local alpha, raw and
  adjusted intervals, seed, iteration count, protocol hash and input hash.

Holm adjusted p-values remain separate lineage for the zero-null family and do
not gate the five-state practical-effect conclusion. Golden tests freeze exact
p-values, Holm local alpha values, simultaneous interval bounds, result hashes
and family hash in
`tests/unit/statistical_methods/test_decision_and_pipeline.py`.

Negative-gain aggregates expose `range_low/range_high`, which are descriptive
min/max envelopes over per-question values. They are not confidence intervals;
any per-question confidence interval remains separate evidence.
