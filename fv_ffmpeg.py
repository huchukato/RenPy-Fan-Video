#!/usr/bin/env python3
"""
RenPy-Fan-Video - ffmpeg/ffprobe path resolver

Le app macOS buildate con PyInstaller non ereditano il PATH
della shell, quindi `subprocess.run(["ffmpeg", ...])` fallisce anche
se ffmpeg e' installato via Homebrew.
"""

from __future__ import annotations

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path


_EXPLICIT_DIRS = [
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/opt/local/bin",
]


def _candidate_paths(binary: str) -> list[Path]:
    candidates: list[Path] = []
    env_var = "FFMPEG_BINARY" if binary == "ffmpeg" else "FFPROBE_BINARY"
    env_val = os.environ.get(env_var)
    if env_val:
        candidates.append(Path(env_val))
    for d in _EXPLICIT_DIRS:
        candidates.append(Path(d) / binary)
    if sys.platform == "darwin":
        exe = Path(sys.executable)
        contents = exe.parent.parent
        if contents.name == "Contents":
            candidates.append(contents / "Resources" / "bin" / binary)
        candidates.append(exe.parent / binary)
    return candidates


@lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in _candidate_paths("ffmpeg"):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


@lru_cache(maxsize=1)
def find_ffprobe() -> str | None:
    found = shutil.which("ffprobe")
    if found:
        return found
    for p in _candidate_paths("ffprobe"):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None
