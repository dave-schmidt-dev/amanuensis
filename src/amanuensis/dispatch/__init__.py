"""Dispatch driver — the LLM-call gating mechanism (M6).

The dispatch package is the operational surface of the LLM-call boundary
defined by INV-4. The cache wrapper (``amanuensis.llm.cached_call``)
enqueues a :class:`DispatchQueueEntry` on a cache miss; this package
provides:

- :mod:`amanuensis.dispatch.queue` — atomic enqueue / dequeue helpers
  plus the routing to ``dispatch/outputs/`` (success) or
  ``dispatch/failures/`` (parse / timeout / write-isolation failure).
- :mod:`amanuensis.dispatch.driver` — harness-CLI detection
  (``shutil.which``) plus the role-invocation primitive that drives a
  Claude / Codex / Cursor / Gemini subprocess.
- :mod:`amanuensis.dispatch.isolation` — workspace-tree mtime snapshot +
  post-invocation walk that enforces CV-5 (a dispatched role must NOT
  mutate any path outside its assigned output directory).

The dispatch driver itself is exposed as the ``amanuensis dispatch`` CLI
command (M6.5). No business logic lives in this ``__init__``; it just
re-exports the stable public surface.
"""

from .driver import InvokeResult, detect_harnesses, invoke_role
from .isolation import assert_no_unauthorized_mutation, snapshot_workspace_tree
from .queue import (
    dequeue,
    enqueue,
    list_queue,
    move_to_failures,
    move_to_outputs,
)

__all__ = [
    "InvokeResult",
    "assert_no_unauthorized_mutation",
    "dequeue",
    "detect_harnesses",
    "enqueue",
    "invoke_role",
    "list_queue",
    "move_to_failures",
    "move_to_outputs",
    "snapshot_workspace_tree",
]
