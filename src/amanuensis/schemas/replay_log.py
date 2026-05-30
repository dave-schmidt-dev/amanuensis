"""ReplayLogEntry — append-only record of a single substrate activity.

The replay log is a workspace-scoped, monotonically-sequenced append
stream describing every activity executed against the substrate. It is
the basis for deterministic replay (M3.x) and cache-hit accounting.

Notes
-----
- ``seq`` is monotonically increasing per workspace; the writer (M1.7)
  guards it with a flock.
- ``inputs_hash`` is the cache key — typically a hash of
  ``(role, prompt, normalized inputs)``. ``outputs_hash`` hashes the
  produced output. M1.5 implements the hashing module.
- ``cache_hit`` is ``True`` iff the activity was satisfied from the
  prior run's outputs without re-executing the role.
- ``substrate_changes`` lists paths written or deleted by the activity.
- Token / cost telemetry fields (``tokens_input``, ``tokens_output``,
  ``cost_estimate_cents``) are OPTIONAL — populated when the harness
  CLI surfaces them, otherwise ``None``. Carrying them now avoids a
  schema-version bump when cost analysis lands.
- ``timestamp`` is tz-aware (``AwareDatetime``).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ._shared import AgentAttribution


class ReplayLogEntry(BaseModel):
    """One append-only entry in a workspace's replay log."""

    model_config = ConfigDict(strict=True, extra="forbid")

    seq: int
    timestamp: AwareDatetime
    actor: AgentAttribution
    activity: str
    inputs_hash: str
    outputs_hash: str
    cache_hit: bool
    substrate_changes: list[str]
    duration_seconds: float

    # Optional cost / capacity telemetry (see module docstring).
    tokens_input: int | None = None
    tokens_output: int | None = None
    cost_estimate_cents: float | None = None

    schema_version: int = 1
