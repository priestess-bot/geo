# Pack 07: migration and operational hardening

Budget: 10h agent time. Status: LOCAL_COMPLETE / BLOCKED_EXTERNAL_FINAL_GATES.

- [x] `P07-01` Verify rolling migration with dual-write or final incremental backfill/reconciliation (2h).
- [x] `P07-02` Enforce sensitive backup permissions, encryption and key isolation before real data (90m).
- [x] `P07-03` Restore PostgreSQL, MinIO and historical Secret/Artifact keyrings into an empty environment (2h).
- [x] `P07-04` Exercise lease loss, worker termination, broker outage, replay and partial object-store failure (2h).
- [x] `P07-05` Freeze load dimensions and latency/queue objectives in the evidence manifest (90m).
- [x] `P07-06` Run migration compatibility, restore canary and performance/fault evidence checks (1h).

Validation and exact receipt hashes are recorded in
[`pack-07-hardening-operations-evidence.md`](pack-07-hardening-operations-evidence.md).
The checked items prove the locally controllable contracts and isolated runtime rehearsals. A full
30-minute production-equivalent performance run, migration of supplied real legacy data, production
key-custodian recovery and independent release signatures remain final external Gates.
