"""Shared YAML-frontmatter helper for skill files.

Skill files are plain Markdown with a YAML frontmatter block fenced by
``---`` on the first line and a matching ``---`` line. Both the skill-
frontmatter validation test and the ``amanuensis distill`` orchestrator
command need to peel off the frontmatter from the body; rather than
duplicate the tiny parser in two places, we expose a single helper here.

The helper is intentionally minimal: no third-party frontmatter library,
no error recovery, no support for alternate fence styles. A malformed
skill file raises ``ValueError`` so the caller surfaces a clear failure
instead of silently parsing the body as YAML.
"""

from __future__ import annotations

from typing import Any

import yaml

_FENCE = "---\n"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a skill file into ``(frontmatter_dict, body)``.

    The file MUST start with a ``---`` fence on line 1, followed by YAML,
    followed by a closing ``---`` fence on its own line. The returned
    ``frontmatter_dict`` is the parsed YAML mapping; the ``body`` is the
    remaining text verbatim (no leading newline strip).

    Raises:
        ValueError: if the file does not begin with a ``---`` fence, if
            no closing fence is present, or if the frontmatter does not
            parse to a YAML mapping.
    """
    if not text.startswith(_FENCE):
        raise ValueError("skill text does not start with '---' frontmatter fence")
    rest = text[len(_FENCE) :]
    closing = rest.find("\n" + _FENCE)
    if closing == -1:
        raise ValueError("skill frontmatter has no closing '---' fence")
    frontmatter_yaml = rest[:closing]
    body = rest[closing + len("\n" + _FENCE) :]
    parsed: Any = yaml.safe_load(frontmatter_yaml)
    if not isinstance(parsed, dict):
        raise ValueError(f"skill frontmatter must parse to a mapping, got {type(parsed).__name__}")
    return parsed, body
