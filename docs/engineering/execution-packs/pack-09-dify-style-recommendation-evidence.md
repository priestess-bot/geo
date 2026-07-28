# Pack 09: Dify Style Profile / Recommendation migration evidence

Status date: 2026-07-28

Status: `LOCAL_COMPLETE / BUSINESS_ACCEPTANCE_BLOCKED_EXTERNAL`

This receipt closes the locally controllable migration of
`synthetic_lab.style_profile` and `recommendations.recommendation` to Dify. It
does not claim a real Style Profile business build or a real Recommendation
business result. Board B remains excluded.

## Source and environment identity

- Branch: `main`.
- Base commit: `d2f729a3cc17c073c68c12a20907c18e2807901e`.
- Uncommitted implementation inventory: 248 modified or new non-documentation
  files, sorted file-content inventory SHA-256
  `11b8f49d60c5c12cd72b27889a7127ceaed13496978ed58c52b4ae9f6de78411`.
- Environment: fresh local staging, Compose project
  `geo-advinsys-staging-v2`.
- Project: `94ec48ea-b2f4-449f-9e93-21c391c66ad0` (`ADVINSYS Australia`).
- Tenant: `10000000-0000-4000-8000-000000000001`.
- Alembic head: `0101_dify_published_identity`.
- Technical owner: `30000000-0000-4000-8000-000000000003`.
- Distinct active enrolment approver:
  `1597f5f8-3c14-4516-85a9-24de94e6ae7c`.
- Independent external verifier: not supplied; final acceptance remains blocked.

The inventory hash intentionally excludes `README.md`, `docs/**` and
`infra/dify/README.md` so this evidence file is not self-referential. It is not
a Git commit and must be replaced by the final commit SHA after the user asks
for a commit.

## Migration identity

| Revision | Up SHA-256 | Down SHA-256 |
|---|---|---|
| `0096_style_recommendation_dify` | `e6f7e75cbac19846aba11cc0ad8eda03352341232d2dfcca20f5f2ffd194e214` | `0d8cd42bf08dc042543c1a12345e1a1f8dec33a343e9f0cc4d779ee00bb1ed1f` |
| `0097_dify_snapshot_fencing` | `4e294f95b1d04f5aefc80a6bdc712b94d7e11b4a7552a9bca286b3dcaf013043` | `8c179d6e92743da3d24ef48e68de3f45fd7041d58c84c91bc931a925388c4607` |
| `0098_synthetic_dify_lineage` | `0903cf987228cbe9cc7b0659d35374cb61f96746df8d100a971c57c2b9f01355` | `cc29416a63f5d228b27843c2d515a15f0f8118635bc5a4e4cf9dac05e31914bf` |
| `0099_style_profile_build_binding` | `e1f0ed359a92c1aa1ee17bea47949f2a6f9de1b8417d0ef878f6d88cf97918f9` | `effa643ac195cc7f7c34fa343196236b165200ce00b5785bfcbb1db4939808b7` |
| `0100_recommendation_type_gate` | `0cbf8e01739ea34509cf81794fdb7e54378aba6dd0d4685967b457d75a565a4d` | `748c04b6c12ccf035819edf9dca9d65b84625f5cda28788872b7190e3a86d0dd` |
| `0101_dify_published_identity` | `8229c1f0aeb78873584f912ff28155ad3f5695ff502699fdd3c768fa1f6d80cf` | `46f01c09b3f73c8bcd9d2a66ddc5b19292b35c6a225713ac39dde89ca76d6790` |

The PostgreSQL suite exercised forward, predecessor, downgrade refusal or
round-trip paths as applicable. `0097` is deliberately a stopped-writer
cutover, not a rolling migration.

## Prompt release evidence

Both five-case suites used real DeepSeek `deepseek-v4-flash` through runtime
selection `5fb95489-9685-5c5b-91c1-eab127a5ce3c`. The frozen policy permits at
most 15 paid calls, meaning five cases with at most three structured-output
attempts per case.

| Purpose | Prompt Release | Version | Job | Result |
|---|---|---:|---|---|
| `synthetic_lab.style_profile` | `dcfa46a6-6202-43ec-a89f-6417b419834e` | 3 | `4334f3ea-7787-5bbc-a751-12b0541d1fae` | 5/5, score 100, result hash `43a483f1d3a713883721d68c840ec6af93c657ea34d6313ee7ea7e77740d8c9e` |
| `recommendations.recommendation` | `33fde865-2d83-4880-a790-60342751bbf4` | 4 | `669feb8c-bfb2-5437-bcff-eb76ef53226d` | 5/5, score 100, result hash `3f14308a2aae486efb92d3c5937278456563e6ced1ebdf75d632e8b79bd67756` |

Style Profile was deliberately retested and republished after the retry-budget
fix; its retired v2 test policy is not used as current evidence.

## Workflow and canary evidence

### Style Profile

- Workflow Release: `1bd26fe3-65ea-4edc-9701-be63d052a8bf`, version 2.
- Release hash:
  `e9d6495c7157d5f149fe412c2d9b3c26697772846621a492182a308389b79970`.
- Dify app/workflow: `4ba22a3a-2278-48a1-85e1-6d8dbf950bc7` /
  `b1801085-c2d9-49c8-b2db-c733355285ef`.
- DSL hash:
  `4dff1020e8bca4db3527dd1a432f259bc4c5bb3448cd033f826aeee9fce46454`.
- Published Snapshot: `1fbd21e0-20fb-4f79-97a0-95fc727a14e6`;
  workflow hash `49f51cefe48bfe1c0aab67c32f876b42b8a5813bab6bbbf0aea3ca141755ecc5`;
  snapshot hash `e4ce3b9c1650ffebe22214fb26baef79acf61a69a3bca57409955903549e8a23`.
- Canary Attempt: `f6b54c2f-f6f0-4ddf-9e71-263c6542d661`;
  Dify task/run `fb341bcd-9a00-46f0-9cec-3e57374b6fdd` /
  `43690b96-b17d-47d1-86c5-5e3d689c6144`.
- Request/context/output hashes:
  `a09714b5559307b543b2e506e5c01956745e6a5f3be2cf569cda09498e2eaf87` /
  `1162a3d2d3df3b4e865d03d5210ad72d3d08843c20979a7b6e8d1ed82de2bc0a` /
  `3d8f3b6bfc41c8308a3432b347829a6baacc4543680d91a8506aa9533f9b7a67`.
- Started/finished: `2026-07-28T10:04:55.291248Z` /
  `2026-07-28T10:04:57.181540Z`; HTTP 200; status `succeeded`.

### Recommendation

- Workflow Release: `f1bbe32d-8657-460b-a788-604167f66219`, version 1.
- Release hash:
  `3262d7a545716849150c9589986a094c6eafa96fb49ff8bfe2e838d0af157bdc`.
- Dify app/workflow: `af97326a-4d87-4172-a48b-41b48da32352` /
  `6e633c40-f1a3-4d37-9498-e89dbeaef1fe`.
- DSL hash:
  `1cc78caac0ad853b543484e3fc3818596d48a64c5a8275dc32cfd8907c862deb`.
- Published Snapshot: `ad54a6ac-76fd-4e62-92c1-797944a93642`;
  workflow hash `49abc2f8954f42081af9fbdb8094de48b1250bee3ec9f41f20670d869cb1b587`;
  snapshot hash `5cbc0811f36c5551e9a9a0ff741ada5090a5817f1cb68aa35ba72108a2ad5210`.
- Canary Attempt: `697741b0-90f4-4c8a-a416-57c15349e2c7`;
  Dify task/run `ecb36af6-55bc-459f-b656-3c4f01741e30` /
  `46125284-abf8-44fe-9958-6e9c8d55604a`.
- Request/context/output hashes:
  `ec892111e5a6da6f77b785568dacd624be42a4bbaf5db22faa02e90c046e49c6` /
  `25adaf500e731a788f457a642c544914b3111ffb6d91e23df15e78254d9f9469` /
  `a8be9cd77896d0cd62dd287c0f85bda466959e9021a81762608ee8f3ff109a08`.
- Started/finished: `2026-07-28T09:17:18.370812Z` /
  `2026-07-28T09:17:20.852984Z`; HTTP 200; status `succeeded`.

Canaries have no Durable Job, lease or fencing generation by design. Business
attempt lease/fence enforcement and one-time unknown-outcome recovery are
covered by the current PostgreSQL integration suite; no business Job ID is
invented for this receipt.

## Verification results

- Required non-live: `2554/2554`, zero failure and zero skip.
- Dify `0095--0101` PostgreSQL integration: `13/13` isolated database tests plus
  `5/5` current staging database tests, zero skip. This includes unknown-outcome
  new-parent recovery, exact Profile result binding, Recommendation type gate,
  RLS, canary activation and migration compatibility.
- Quality: Ruff; MyPy `780` source files; six Web workspace typechecks; secret
  scan `2158` files; architecture `43/43`.
- Stable OpenAPI: `7/7`.
- Web: auth contract `4/4`; Admin and Customer production builds passed.
- Chromium: Admin `30/30`, Customer `12/12`, Workflow C `6/6`; total `48/48`,
  zero skip/flaky.
- Infrastructure: contracts `73/73`, production network `2/2`, isolated Docker
  runtime `7/7`.
- Fresh-volume MinIO initializer: all five governed buckets were created
  idempotently; the isolated container, network and volume were removed.
- Live Admin: desktop `1440x1000` and mobile `390x844` each showed ten active,
  ten current, ten published Prompt nodes and ten Dify links; HTTP 200, no
  horizontal overflow, console error or page error.
- Runtime API: `runtime_backend=dify`, `10/10 active`, `10/10 current`,
  `10/10 last canary succeeded`; Internal and Customer `/ready` both returned
  ready.
- Authenticated empty-environment restore:
  `artifacts/backup-restore-smoke-authenticated/20260728T075555Z-226023`, head
  `0101`, 245 tables, 111 non-B relations, 101 migration checksums and five
  buckets/12 objects. Receipt SHA-256
  `f73ce0a03da3dd4e04e5edf731b0db2a9069e0514ce4f29439d393981128c606`;
  manifest SHA-256
  `38c64280bf1d8c0be4c9c6a7ed61dbf1b21e210f9b01e4bbcc891b8bf1f2f9df`.

The executor classifies an HTTP 5xx after submission as a terminal
`unknown_outcome`; the PostgreSQL recovery test proves the old parent is never
reopened, an active lease blocks reconciliation, one human-issued token binds
one new matching parent, and replay/forged tokens fail. This is controlled
technical evidence, not a claim that a real external provider failed during a
business run.

## Inputs still required together at final acceptance

- Lawfully collected, deduplicated, anonymised and human-approved Australian
  English Style Samples: at least 200 per platform and at least 24 eligible
  examples in a frozen Profile build input.
- One real Style Profile business Job with Collection Run, Sample, Profile
  Version, exact build binding, Dify attempt/run and saved business result.
- One real Recommendation business Job with selected approved
  Observation/Statistic/Fact/Rule evidence, evidence graph hash, final
  Recommendation/result IDs and Dify attempt/run.
- Production-equivalent topology, production key custodian, Dify deployment
  licence confirmation and an independent verifier signature.

Until these inputs arrive, the implementation checklist may be complete while
the corresponding business and final roadmap Gates remain
`BLOCKED_EXTERNAL`/unchecked.
