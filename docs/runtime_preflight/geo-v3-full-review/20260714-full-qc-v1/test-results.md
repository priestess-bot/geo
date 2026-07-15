# Test Results - 20260714-full-qc-v1

| Check | Result | Evidence |
| --- | --- | --- |
| Nine channel coverage | PASS | 9 tasks: 6 approved, 3 needs evidence |
| Real model generation | PASS | 6 final packages retain `deepseek-chat` response hashes |
| Independent review | PASS | All 6 approved packages have a score of at least 85 |
| Negative contracts | PASSED | `negative-tests.json` |
| No publication side effect | PASS | Submission count 1 -> 1 |
| GEO runtime/schema contracts | PASS | 17/17 unit tests |
| Durable lease contracts | PASS | 15/15 unit tests in API image |
| Admin Web typecheck/build | PASS | Next.js production build includes `/projects/[project_id]/geo` |
| Customer Web typecheck/build | PASS | Next.js production build completed |
| Migration idempotency | PASS | All migrations reran; zero unvalidated GEO project FKs |
| Browser workflow | PASS | Desktop, tablet and mobile flow; Markdown export; zero horizontal overflow |
| Service health | PASS | API health OK; Admin and Customer HTTP 200 |
| Worktree whitespace | PASS | `git diff --check` returned no findings |

## Browser evidence

- `docs/runtime_preflight/geo-v3-admin-workspace.png`
- `docs/runtime_preflight/geo-v3-admin-workspace-tablet.png`
- `docs/runtime_preflight/geo-v3-admin-workspace-mobile.png`

## Database invariants

- Nine Destination tasks exist: six `approved`, three `candidate`.
- Candidate tasks have zero Opportunities and therefore cannot generate packages.
- All six final packages are `approved`, have `qa_status=passed`, score at least 85, a distinct reviewer, complete Claims, and valid Prompt/response hashes.
- Submission count remained 1 and verified Submission count remained 0.
