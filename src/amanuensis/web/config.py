"""Web-app configuration.

Reads bind host / port from environment variables, falling back to
``127.0.0.1`` / ``8723``. The ``127.0.0.1`` default is deliberate: the
supervisor workflow assumes the human is on the same machine as the
substrate.

M8.8 enforces this policy at config-load time: :func:`load_config` calls
:func:`validate_bind_host` and refuses non-loopback bind targets unless
the supervisor explicitly opts in via ``AMANUENSIS_ALLOW_PUBLIC_BIND``.
The substrate may contain privileged client matter; exposing it on
``0.0.0.0`` to anyone on the network is a footgun we surface loudly
rather than allow silently.

Environment variables
---------------------
``AMANUENSIS_HOST``
    Bind host. Defaults to ``127.0.0.1``. Mirrors ``.env.example``.
``AMANUENSIS_PORT``
    Bind port. Defaults to ``8723``. Must be a valid integer 1-65535.
``AMANUENSIS_ALLOW_PUBLIC_BIND``
    Opt-in override (``1`` / ``true``, case-insensitive) that allows
    binding to non-loopback addresses (``0.0.0.0``, ``::``, an external
    IP, etc.). Default is unset, which means non-loopback bindings raise
    :class:`BindHostNotAllowed`.

The legacy / spec-document names ``AMANUENSIS_BIND_HOST`` and
``AMANUENSIS_BIND_PORT`` are accepted as fallbacks for compatibility
with the M8 design doc (the canonical names in ``.env.example`` are the
shorter forms).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "BindHostNotAllowed",
    "WebConfig",
    "load_config",
    "validate_bind_host",
]

# Loopback bind targets accepted without an explicit override. String
# match is intentional for Phase 1 — see ``validate_bind_host`` docstring.
_LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "::1", "localhost"})

# Env var the user would set to opt-in to non-loopback binding. Named as
# a module constant so error messages and the env-var check stay in sync.
_ALLOW_PUBLIC_ENV_VAR = "AMANUENSIS_ALLOW_PUBLIC_BIND"


class BindHostNotAllowed(ValueError):
    """Raised when a non-loopback bind host is requested without opt-in.

    Subclasses :class:`ValueError` because the offending input is a
    configuration value, not a programming error. Callers that want to
    catch *only* this case (vs. any bad config) can match the subclass.
    """


@dataclass(frozen=True)
class WebConfig:
    """Web-app runtime configuration.

    Frozen so the FastAPI app cannot mutate it at request time; reload
    by re-calling :func:`load_config` (which is invoked once in the
    lifespan startup).
    """

    bind_host: str = "127.0.0.1"
    bind_port: int = 8723


def validate_bind_host(host: str, *, allow_public: bool = False) -> str:
    """Reject non-loopback bind targets unless explicitly allowed.

    Default policy: bind targets MUST be loopback (``127.0.0.1``, ``::1``,
    ``localhost``). Public/network targets (``0.0.0.0``, ``::``, ``*``,
    any external IP, any other hostname) require explicit
    ``allow_public=True`` opt-in.

    Phase-1 matching is purely lexical — we compare ``host`` against a
    small set of literal loopback strings rather than resolving the
    hostname via DNS. DNS resolution would couple correctness to the
    supervisor's resolver state and could fail open if a hostile resolver
    pointed ``localhost`` at a public address. A small literal set is
    both safer and faster.

    Args:
        host: The bind host string the supervisor (or env var) requested.
        allow_public: If True, skip the loopback check and return ``host``
            unchanged. The caller (``load_config``) gates this on the
            ``AMANUENSIS_ALLOW_PUBLIC_BIND`` env var.

    Returns:
        ``host`` unchanged when validation succeeds.

    Raises:
        BindHostNotAllowed: When ``host`` is not a recognized loopback
            address and ``allow_public`` is False. The message names the
            override env var so the supervisor can find it without
            re-reading the docs.
    """
    if allow_public:
        return host
    if host in _LOOPBACK_HOSTS:
        return host
    raise BindHostNotAllowed(
        f"Refusing to bind to non-loopback host {host!r}. The web app "
        "defaults to 127.0.0.1 because the substrate may contain "
        "privileged matter. To explicitly bind to a public/network "
        f"address, set {_ALLOW_PUBLIC_ENV_VAR}=1 in the environment."
    )


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


def _read_allow_public(raw: str | None) -> bool:
    """Parse the ``AMANUENSIS_ALLOW_PUBLIC_BIND`` env var.

    Truthy values (case-insensitive): ``1``, ``true``. Everything else
    — including unset, empty string, ``0``, ``false``, ``no`` — is False.
    Mirrors the conservative interpretation: opting *in* to a security
    relaxation requires a deliberate, unambiguous value.
    """
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true"}


def load_config() -> WebConfig:
    """Load :class:`WebConfig` from the process environment.

    Precedence per field: ``AMANUENSIS_HOST`` then
    ``AMANUENSIS_BIND_HOST`` then the default. Same shape for port.

    The resolved ``bind_host`` is passed through :func:`validate_bind_host`
    so a misconfigured ``AMANUENSIS_HOST=0.0.0.0`` raises
    :class:`BindHostNotAllowed` at config-load time, before the FastAPI
    app starts.
    """
    host = (
        os.environ.get("AMANUENSIS_HOST") or os.environ.get("AMANUENSIS_BIND_HOST") or "127.0.0.1"
    )
    port_raw = os.environ.get("AMANUENSIS_PORT") or os.environ.get("AMANUENSIS_BIND_PORT")
    port = _read_port(port_raw, 8723)
    allow_public = _read_allow_public(os.environ.get(_ALLOW_PUBLIC_ENV_VAR))
    validated_host = validate_bind_host(host, allow_public=allow_public)
    return WebConfig(bind_host=validated_host, bind_port=port)
