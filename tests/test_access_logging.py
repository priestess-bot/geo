from __future__ import annotations

import unittest
from uuid import uuid4

from starlette.requests import Request

from geno_api.access_logging import extract_project_id_from_request


def _request(path: str, query_string: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": query_string.encode("utf-8"),
            "headers": [],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


class AccessLoggingTest(unittest.TestCase):
    def test_extract_project_id_ignores_market_slug_project_create_path(self) -> None:
        request = _request("/v1/projects/runtime/au/dtc-ecommerce")

        self.assertIsNone(extract_project_id_from_request(request))

    def test_extract_project_id_accepts_uuid_query_parameter(self) -> None:
        project_id = str(uuid4())
        request = _request("/v1/visibility-scores/runtime", f"project_id={project_id}")

        self.assertEqual(extract_project_id_from_request(request), project_id)

    def test_extract_project_id_ignores_invalid_query_parameter(self) -> None:
        request = _request("/v1/visibility-scores/runtime", "project_id=au")

        self.assertIsNone(extract_project_id_from_request(request))

    def test_extract_project_id_accepts_uuid_project_path(self) -> None:
        project_id = str(uuid4())
        request = _request(f"/v1/projects/runtime/{project_id}")

        self.assertEqual(extract_project_id_from_request(request), project_id)


if __name__ == "__main__":
    unittest.main()
