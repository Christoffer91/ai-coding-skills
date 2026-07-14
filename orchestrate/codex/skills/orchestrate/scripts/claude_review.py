#!/usr/bin/env python3
"""Dispatch to the canonical Claude review runner shipped by dotfiles."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> None:
    override = os.environ.get("ORCH_CLAUDE_REVIEW_HELPER")
    candidates = [Path(override)] if override else []
    here = Path(__file__).resolve()
    candidates.extend((
        here.parents[5] / "scripts/claude_review.py",
        here.parents[4] / "scripts/claude_review.py",
        Path.home() / "dev/repos/dotfiles/scripts/claude_review.py",
    ))
    for candidate in candidates:
        if candidate.is_file() and candidate.resolve() != here:
            os.execv(sys.executable, [sys.executable, str(candidate), *sys.argv[1:]])
    raise SystemExit("canonical Claude review runner not found")


if __name__ == "__main__":
    main()
