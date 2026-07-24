from email.message import EmailMessage

import pytest

from geo_alert_smtp_relay.__main__ import RelayConfig, _validated_message


def _environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    username = tmp_path / "username"
    password = tmp_path / "password"
    username.write_text("relay-user", encoding="utf-8")
    password.write_text("relay-password", encoding="utf-8")
    values = {
        "GEO_ALERT_SMTP_UPSTREAM_HOST": "smtp.example.test",
        "GEO_ALERT_SMTP_UPSTREAM_ALLOWED_HOSTS": "smtp.example.test",
        "GEO_ALERT_SMTP_TLS_MODE": "starttls",
        "GEO_ALERT_SMTP_USERNAME_FILE": str(username),
        "GEO_ALERT_SMTP_PASSWORD_FILE": str(password),
        "GEO_ALERT_SMTP_SENDER": "geo-alerts@example.test",
        "GEO_ALERT_SMTP_RECIPIENTS": "ops@example.test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def test_relay_config_requires_exact_upstream_allowlist_and_secret_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _environment(monkeypatch, tmp_path)
    config = RelayConfig.from_environment()

    assert config.upstream_host == "smtp.example.test"
    assert config.upstream_port == 587
    assert config.allowed_recipients == frozenset({"ops@example.test"})
    monkeypatch.setenv("GEO_ALERT_SMTP_UPSTREAM_HOST", "forged.example.test")
    with pytest.raises(RuntimeError, match="allowlisted"):
        RelayConfig.from_environment()


def test_relay_rejects_direct_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv("GEO_ALERT_SMTP_PASSWORD", "must-not-enter-environment")

    with pytest.raises(RuntimeError, match="direct secret values are forbidden"):
        RelayConfig.from_environment()


def test_relay_accepts_only_the_frozen_sender_and_recipient_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _environment(monkeypatch, tmp_path)
    config = RelayConfig.from_environment()
    message = EmailMessage()
    message["From"] = config.allowed_sender
    message["To"] = "ops@example.test"
    message["Subject"] = "sanitized alert"
    message.set_content("Only the approved summary is present.")

    parsed = _validated_message(
        message.as_bytes(),
        sender=config.allowed_sender,
        recipients=("ops@example.test",),
        config=config,
    )
    assert parsed["Subject"] == "sanitized alert"

    message["Bcc"] = "hidden@example.test"
    with pytest.raises(ValueError, match="envelope differs"):
        _validated_message(
            message.as_bytes(),
            sender=config.allowed_sender,
            recipients=("ops@example.test",),
            config=config,
        )
