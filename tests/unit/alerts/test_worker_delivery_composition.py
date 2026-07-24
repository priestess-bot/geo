from pathlib import Path

import pytest

from geo_core.alerts import NotificationChannel
from geo_worker.workflow_c_delivery import build_workflow_c_notification_dispatcher


class _Inbox:
    def put(self, **_values: object) -> None:
        return None


def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    secret = tmp_path / "webhook-secret"
    secret.write_text("webhook-signing-key", encoding="utf-8")
    values = {
        "GEO_ALERT_SMTP_HOST": "alert-smtp-relay",
        "GEO_ALERT_SMTP_PORT": "8025",
        "GEO_ALERT_SMTP_SENDER": "geo@example.test",
        "GEO_ALERT_SMTP_RECIPIENTS": "ops@example.test",
        "GEO_ALERT_WEBHOOK_ENDPOINT": "https://alerts.intranet.test/hooks/geo",
        "GEO_ALERT_WEBHOOK_ALLOWED_HOSTS": "alerts.intranet.test",
        "GEO_ALERT_WEBHOOK_SIGNING_SECRET_FILE": str(secret),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_worker_delivery_composition_installs_all_three_channels(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)

    dispatcher = build_workflow_c_notification_dispatcher(inbox_writer=_Inbox())

    assert set(dispatcher._transports) == {  # noqa: SLF001 - composition contract
        NotificationChannel.ADMIN_INBOX,
        NotificationChannel.LOCAL_SMTP,
        NotificationChannel.INTERNAL_WEBHOOK,
    }


def test_worker_delivery_composition_rejects_arbitrary_smtp_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv("GEO_ALERT_SMTP_HOST", "smtp.attacker.test")

    with pytest.raises(RuntimeError, match="fixed alert-smtp-relay"):
        build_workflow_c_notification_dispatcher(inbox_writer=_Inbox())
