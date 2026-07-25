from pathlib import Path

import pytest

from geo_core.alerts.delivery import AlertRuleViolation, HttpxWebhookClient


def test_webhook_client_rejects_missing_or_symlinked_ca_files(tmp_path: Path) -> None:
    with pytest.raises(AlertRuleViolation, match="CA file"):
        HttpxWebhookClient(ca_file=tmp_path / "missing.pem")

    certificate = tmp_path / "certificate.pem"
    certificate.write_text("placeholder", encoding="ascii")
    link = tmp_path / "certificate-link.pem"
    link.symlink_to(certificate)
    with pytest.raises(AlertRuleViolation, match="CA file"):
        HttpxWebhookClient(ca_file=link)


def test_webhook_client_passes_explicit_ca_only_to_webhook_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    certificate = tmp_path / "certificate.pem"
    certificate.write_text("placeholder", encoding="ascii")
    observed: dict[str, object] = {}

    class _Response:
        status_code = 204
        headers = {"x-test": "ok"}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object):
            return _Response()

    def factory(**kwargs: object) -> _Client:
        observed.update(kwargs)
        return _Client()

    monkeypatch.setattr("geo_core.alerts.delivery.httpx.Client", factory)
    response = HttpxWebhookClient(ca_file=certificate).post(
        "https://alerts.example.test/hooks",
        content=b"{}",
        headers={},
        timeout_seconds=1,
        follow_redirects=False,
    )

    assert response.status_code == 204
    assert observed["verify"] == str(certificate)
