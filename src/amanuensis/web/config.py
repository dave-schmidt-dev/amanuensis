"""Web-app configuration.

Reads bind host / port from environment variables, falling back to
``127.0.0.1`` / ``8723``. The ``127.0.0.1`` default is deliberate: the
supervisor workflow assumes the human is on the same machine as the
substrate. M8.8 will add an explicit refusal for ``0.0.0.0`` /
publicly-routable bindings.

Environment variables
---------------------
``AMANUENSIS_HOST``
    Bind host. Defaults to ``127.0.0.1``. Mirrors ``.env.example``.
``AMANUENSIS_PORT``
    Bind port. Defaults to ``8723``. Must be a valid integer 1-65535.

The legacy / spec-document names ``AMANUENSIS_BIND_HOST`` and
``AMANUENSIS_BIND_PORT`` are accepted as fallbacks for compatibility
with the M8 design doc (the canonical names in ``.env.example`` are the
shorter forms).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebConfig:
    """Web-app runtime configuration.

    Frozen so the FastAPI app cannot mutate it at request time; reload
    by re-calling :func:`load_config` (which is invoked once in the
    lifespan startup).
    """

    bind_host: str = "127.0.0.1"
    bind_port: int = 8723


def _read_port(raw: str | None, default: int) -> int:
    """Parse a port env var, falling back to ``default`` on bad input.

    Strict parsing — empty string and non-integers both fall back. We
    deliberately do not raise: a misconfigured env var should not crash
    the app at import time; the supervisor will see the wrong port and
    fix it.
    """
    if raw is None or raw.strip() == "":
        return default
    try:
        port = int(raw)
    except ValueError:
        return default
    if not (1 <= port <= 65535):
        return default
    return port


def load_config() -> WebConfig:
    """Load :class:`WebConfig` from the process environment.

    Precedence per field: ``AMANUENSIS_HOST`` then
    ``AMANUENSIS_BIND_HOST`` then the default. Same shape for port.
    """
    host = (
        os.environ.get("AMANUENSIS_HOST") or os.environ.get("AMANUENSIS_BIND_HOST") or "127.0.0.1"
    )
    port_raw = os.environ.get("AMANUENSIS_PORT") or os.environ.get("AMANUENSIS_BIND_PORT")
    port = _read_port(port_raw, 8723)
    return WebConfig(bind_host=host, bind_port=port)
