"""M8.8 — localhost-only binding policy.

Asserts that:

- :class:`WebConfig` defaults to ``127.0.0.1``.
- :func:`validate_bind_host` accepts loopback addresses (``127.0.0.1``,
  ``::1``, ``localhost``) without raising.
- Non-loopback addresses (``0.0.0.0``, arbitrary external IPs) are
  refused by default with a :class:`BindHostNotAllowed` whose message
  names the override env var.
- The ``allow_public=True`` kwarg suppresses the refusal.
- :func:`load_config` enforces the same policy when reading
  ``AMANUENSIS_HOST`` from the environment, and respects the
  ``AMANUENSIS_ALLOW_PUBLIC_BIND`` opt-in.

These tests are pure-Python (no FastAPI / TestClient) because the
policy fires at config-load time, before the app is constructed.
"""

from __future__ import annotations

import pytest

from amanuensis.web.config import (
    BindHostNotAllowed,
    WebConfig,
    load_config,
    validate_bind_host,
)


def test_default_config_is_loopback() -> None:
    """``WebConfig()`` (no args) binds to ``127.0.0.1``."""
    config = WebConfig()
    assert config.bind_host == "127.0.0.1"


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_addresses_pass_validation(host: str) -> None:
    """All three documented loopback strings round-trip unchanged."""
    assert validate_bind_host(host) == host


def test_zeroes_address_refused_by_default() -> None:
    """``0.0.0.0`` raises ``BindHostNotAllowed`` and names the override env var."""
    with pytest.raises(BindHostNotAllowed) as exc_info:
        validate_bind_host("0.0.0.0")
    # The error message must point the supervisor at the opt-in knob,
    # otherwise they have to grep the source to find out how to override.
    assert "AMANUENSIS_ALLOW_PUBLIC_BIND" in str(exc_info.value)
    # And it must mention the offending host so the message is actionable
    # when buried in a stack trace.
    assert "0.0.0.0" in str(exc_info.value)


def test_explicit_override_allows_zeroes_address() -> None:
    """``allow_public=True`` short-circuits the loopback check."""
    assert validate_bind_host("0.0.0.0", allow_public=True) == "0.0.0.0"


def test_load_config_refuses_zeroes_address_via_env_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AMANUENSIS_HOST=0.0.0.0`` alone must raise — no silent fall-through."""
    monkeypatch.setenv("AMANUENSIS_HOST", "0.0.0.0")
    # Belt-and-braces: ensure no stray override env from the outer shell
    # turns this test into a no-op.
    monkeypatch.delenv("AMANUENSIS_ALLOW_PUBLIC_BIND", raising=False)
    with pytest.raises(BindHostNotAllowed):
        load_config()


def test_load_config_allows_zeroes_address_with_override_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting BOTH env vars yields a config bound to ``0.0.0.0``."""
    monkeypatch.setenv("AMANUENSIS_HOST", "0.0.0.0")
    monkeypatch.setenv("AMANUENSIS_ALLOW_PUBLIC_BIND", "1")
    config = load_config()
    assert config.bind_host == "0.0.0.0"


def test_arbitrary_external_ip_refused_by_default() -> None:
    """A plausible-looking LAN IP is still non-loopback and must raise."""
    with pytest.raises(BindHostNotAllowed):
        validate_bind_host("192.168.1.5")
