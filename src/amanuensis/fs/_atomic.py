"""Atomic write helper for substrate artifacts.

INV-8 mandates that substrate readers never observe a torn write. We
satisfy this with the standard write-to-tmp-then-rename pattern:

1. Ensure the parent directory exists.
2. Write the new bytes to a sibling temp path
   (``<final-path>.tmp.<pid>.<random>``).
3. fsync the temp file so the bytes are durable before rename.
4. ``os.replace`` the temp file over the final path. On POSIX,
   ``replace`` is atomic with respect to readers: a concurrent reader
   sees either the previous file (if any) or the new file, never an
   intermediate state.

The temp-name template includes the writer's PID and a random suffix so
two concurrent writers targeting the same canonical path never collide
on their tmp file (even before flock arrives in M1.8).

Crash semantics: if the writer crashes between step 2 and step 4, the
canonical path is untouched (either nonexistent or holding the prior
content), and the ``.tmp.*`` sibling is an orphan that the caller (or a
sweep) can remove. The canonical path never holds a half-written file.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Atomically write a UTF-8 text payload to ``path``.

    Args:
        path: Final canonical path. Parent directories are created on
            demand. Must be the path the caller wants readers to see;
            this function does not interpret it semantically.
        content: UTF-8 text payload. Encoding is fixed (utf-8); callers
            wanting other encodings must build their own helper.

    Side effects:
        - Creates ``path.parent`` if missing (``mkdir(parents=True,
          exist_ok=True)``).
        - Writes a sibling ``.tmp.<pid>.<rand>`` file briefly during the
          write window.

    Crash safety:
        If the process dies before ``os.replace`` runs, the canonical
        ``path`` is untouched. The ``.tmp.*`` sibling may persist as an
        orphan; this is recoverable (just unlink).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f"{path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
    tmp = path.parent / tmp_name
    # Write + fsync + rename. We open with mode "w" so an unexpected
    # leftover of the same name (vanishingly unlikely given the pid +
    # random tag) is truncated rather than appended to.
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
