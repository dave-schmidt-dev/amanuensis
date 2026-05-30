"""Route modules for the amanuensis web app.

Each module defines one ``APIRouter`` registered onto the FastAPI app in
:func:`amanuensis.web.app.create_app`. Routes are read-only in M8.2;
M8.5 adds POST handlers for clarifications / iterations behind the
workspace flock.
"""

from __future__ import annotations
