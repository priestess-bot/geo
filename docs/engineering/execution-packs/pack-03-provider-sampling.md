# Pack 03: five Provider sampling releases

Budget: 10h agent time. Status: `LOCAL_COMPLETE / BLOCKED_EXTERNAL`.

- [x] `P03-01` Audit and freeze OpenAI, Gemini, Perplexity, Microsoft and Kimi adapter release contracts (90m).
- [x] `P03-02` Complete provider-specific structured extraction, citation and grounding normalization (2h).
- [x] `P03-03` Enforce Secret Reference, budgets, rate limits and artifact lineage across all adapters (2h).
- [x] `P03-04` Add replayable per-provider canary harness and redacted evidence manifest (2h).
- [x] `P03-05` Verify cancellation, lease loss, retry, invalid response and quota exhaustion (90m).
- [x] `P03-06` Run quality and record unavailable credentials as consolidated non-blocking needs (1h).

Validation: adapter contract tests, governed Sampling integration and opt-in live canaries. A provider without supplied credentials remains `BLOCKED_EXTERNAL`, never fixture-complete.

Local evidence: [pack-03-provider-sampling-evidence.md](pack-03-provider-sampling-evidence.md). All six checkboxes describe locally controllable implementation and verification. Five real Provider manifests and maker/checker publication remain external acceptance evidence and are deliberately not claimed here.
