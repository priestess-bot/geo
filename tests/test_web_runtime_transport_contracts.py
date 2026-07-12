from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "apps/admin-web"
CUSTOMER = ROOT / "apps/customer-web"


class WebRuntimeTransportContractTests(unittest.TestCase):
    def test_admin_and_customer_transport_contracts_are_byte_identical(self) -> None:
        admin = (ADMIN / "app/_runtime/contracts.ts").read_bytes()
        customer = (CUSTOMER / "app/_runtime/contracts.ts").read_bytes()
        self.assertEqual(hashlib.sha256(admin).hexdigest(), hashlib.sha256(customer).hexdigest())
        self.assertEqual(admin, customer)

    def test_runtime_entrypoints_delegate_to_typed_transport(self) -> None:
        for app in (ADMIN, CUSTOMER):
            runtime = (app / "app/runtime.ts").read_text(encoding="utf-8")
            self.assertIn("export async function runtimeHttpRequest<T>", runtime)
            self.assertIn("RuntimeRequestOptions = RuntimeRequestGuards", runtime)
            self.assertIn("runtimeGuardHeaders(options)", runtime)
            self.assertIn("performRuntimeHttpRequest<T>", runtime)
            self.assertIn("options.body !== undefined", runtime)
            self.assertIn("problem:", runtime)

    def test_transport_contract_executes_header_and_response_semantics(self) -> None:
        node_script = r"""
const contract = require(process.argv[1]);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const guards = contract.runtimeGuardHeaders({
    ifMatch: '"head-v2"',
    idempotencyKey: "create-asset-version-1"
  });
  assert(guards["If-Match"] === '"head-v2"', "If-Match was not preserved");
  assert(
    guards["Idempotency-Key"] === "create-asset-version-1",
    "Idempotency-Key was not preserved"
  );
  for (const invalid of ["", "  ", "bad\nheader", "bad\rheader"]) {
    let rejected = false;
    try {
      contract.runtimeGuardHeaders({ idempotencyKey: invalid });
    } catch (error) {
      rejected = error instanceof TypeError;
    }
    assert(rejected, `invalid command header was accepted: ${JSON.stringify(invalid)}`);
  }

  const accepted = await contract.performRuntimeHttpRequest(
    "https://api.example.test/jobs",
    { method: "POST", headers: guards },
    async (_input, init) => {
      assert(init.headers["If-Match"] === '"head-v2"', "fetch lost If-Match");
      assert(
        init.headers["Idempotency-Key"] === "create-asset-version-1",
        "fetch lost Idempotency-Key"
      );
      return new Response(JSON.stringify({ job_id: "job-1", correlation_id: "operation-1" }), {
        status: 202,
        headers: {
          "Content-Type": "application/json",
          ETag: '"job-v1"',
          Location: "/v1/jobs/job-1",
          "Retry-After": "3",
          "X-GENO-Request-Id": "request-1"
        }
      });
    }
  );
  assert(accepted.ok, "202 response was not successful");
  assert(accepted.data.job_id === "job-1", "JSON payload was not parsed");
  assert(accepted.response.etag === '"job-v1"', "ETag was not preserved");
  assert(accepted.response.location === "/v1/jobs/job-1", "Location was not preserved");
  assert(accepted.response.retryAfter === "3", "Retry-After was not preserved");
  assert(accepted.response.correlationId === "operation-1", "correlation ID was not preserved");
  assert(accepted.response.requestId === "request-1", "request ID was not preserved");

  const conflict = await contract.performRuntimeHttpRequest(
    "https://api.example.test/assets/asset-1",
    { method: "POST" },
    async () => new Response(JSON.stringify({
      code: "content_hash_mismatch",
      detail: "The asset head changed.",
      correlation_id: "operation-2",
      retryable: false
    }), {
      status: 412,
      headers: { "Content-Type": "application/problem+json", ETag: '"head-v3"' }
    })
  );
  assert(!conflict.ok && conflict.status === 412, "412 was not a typed failure");
  assert(conflict.error.code === "content_hash_mismatch", "stable error code was lost");
  assert(conflict.error.detail === "The asset head changed.", "error detail was lost");
  assert(conflict.error.correlation_id === "operation-2", "error correlation ID was lost");
  assert(conflict.error.retryable === false, "retryability was lost");
  assert(conflict.response.etag === '"head-v3"', "failure ETag was not preserved");

  const noContent = await contract.performRuntimeHttpRequest(
    "https://api.example.test/jobs/job-1",
    { method: "DELETE" },
    async () => new Response(null, { status: 204, headers: { "X-Request-Id": "request-3" } })
  );
  assert(noContent.ok && noContent.data === undefined, "204 response was not handled");
  assert(noContent.response.correlationId === "request-3", "request correlation fallback was lost");

  const unavailable = await contract.performRuntimeHttpRequest(
    "https://api.example.test/jobs",
    { method: "GET" },
    async () => { throw new Error("network unavailable"); }
  );
  assert(!unavailable.ok, "network failure was not returned as a typed failure");
  assert(unavailable.error.code === "runtime_upstream_unavailable", "network error code changed");
  assert(unavailable.error.retryable === true, "network failure was not retryable");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""
        with tempfile.TemporaryDirectory(prefix="web-runtime-transport-") as temp:
            temp_path = Path(temp)
            for app in (ADMIN, CUSTOMER):
                output = temp_path / app.name
                subprocess.run(
                    [
                        str(app / "node_modules/.bin/tsc"),
                        str(app / "app/_runtime/contracts.ts"),
                        "--outDir",
                        str(output),
                        "--module",
                        "commonjs",
                        "--moduleResolution",
                        "node",
                        "--target",
                        "ES2022",
                        "--lib",
                        "ES2022,DOM",
                        "--skipLibCheck",
                    ],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["node", "-e", node_script, str(output / "contracts.js")],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )


if __name__ == "__main__":
    unittest.main()
