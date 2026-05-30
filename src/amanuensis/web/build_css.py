"""Tailwind build entry point.

Runs ``pytailwindcss`` (which ships the standalone Tailwind binary in a
Python package — no Node toolchain needed) over
``src/amanuensis/web/tailwind.input.css`` and writes the result to
``src/amanuensis/web/static/tailwind.css``.

Invoke with::

    uv run --no-sync python -m amanuensis.web.build_css

The output file is committed (so the wheel ships with a pre-built CSS
and end users don't need to run the build at install time). Re-run
this whenever templates change so unused utility classes get tree-
shaken back out.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytailwindcss  # pyright: ignore[reportMissingTypeStubs]

_WEB_ROOT = Path(__file__).resolve().parent
_INPUT = _WEB_ROOT / "tailwind.input.css"
_OUTPUT = _WEB_ROOT / "static" / "tailwind.css"
_CONFIG = _WEB_ROOT / "tailwind.config.js"


def build(*, minify: bool = True) -> Path:
    """Run Tailwind and return the output path.

    Parameters
    ----------
    minify
        If True (default), produce minified CSS. Set to False when
        debugging template scanning / extracted utilities.

    Returns
    -------
    Path
        Absolute path to the generated CSS file.

    Raises
    ------
    RuntimeError
        If the Tailwind binary exits non-zero (printed to stderr by
        ``live_output=True``).
    """
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    args = [
        "--input",
        str(_INPUT),
        "--output",
        str(_OUTPUT),
        "--config",
        str(_CONFIG),
    ]
    if minify:
        args.append("--minify")

    # ``auto_install=True`` fetches the Tailwind binary on first run.
    # We pin via TAILWINDCSS_VERSION env var if needed; default is the
    # latest stable, which is what pytailwindcss documents.
    # pytailwindcss ships no type stubs; the call returns Any. When
    # ``live_output=True``, ``run`` returns the CompletedProcess
    # directly; otherwise it returns stripped stdout. Treat the result
    # opaquely and probe ``returncode`` defensively.
    result = pytailwindcss.run(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        args,
        cwd=str(_WEB_ROOT.parent.parent.parent),  # project root
        live_output=True,
        auto_install=True,
    )

    returncode_obj = getattr(result, "returncode", 0)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
    returncode = returncode_obj if isinstance(returncode_obj, int) else 0
    if returncode != 0:
        raise RuntimeError(f"tailwindcss build failed with exit code {returncode}")

    return _OUTPUT


def main() -> int:
    """CLI entry point — returns a shell exit code."""
    try:
        out = build()
    except (RuntimeError, OSError) as exc:
        print(f"tailwind build failed: {exc}", file=sys.stderr)
        return 1
    size = out.stat().st_size if out.exists() else 0
    print(f"wrote {out} ({size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
