"""Filesystem locations used by the bridge."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

HOME = Path.home()
STATE_DIR = Path(os.environ.get("AGY_BRIDGE_HOME", HOME / ".agy-bridge"))
SESSIONS_FILE = STATE_DIR / "sessions.json"
LOG_DIR = STATE_DIR / "logs"
SCRATCH_DIR = STATE_DIR / "scratch"
CACHE_FILE = STATE_DIR / "cache.json"

GEMINI_CONFIG_DIR = HOME / ".gemini" / "config"
GLOBAL_AGENTS_DIR = GEMINI_CONFIG_DIR / "agents"
GLOBAL_SKILLS_DIR = GEMINI_CONFIG_DIR / "skills"
CLAUDE_SKILLS_DIR = HOME / ".claude" / "skills"
INSTALL_MANIFEST = STATE_DIR / "install.json"

# Logs hold full review transcripts, including the user's code, so they are opt-in.
LOGGING = os.environ.get("AGY_BRIDGE_LOG", "").strip().lower() not in ("", "0", "false", "no")


def ensure_dirs() -> None:
    for d in (STATE_DIR, SCRATCH_DIR, *([LOG_DIR] if LOGGING else [])):
        d.mkdir(parents=True, exist_ok=True)


def agy_binary() -> str:
    """Resolve the agy executable: $AGY_BIN, ~/.gemini/bin/agy, then PATH."""
    env = os.environ.get("AGY_BIN")
    if env:
        exe = os.path.expanduser(env)
        if not os.access(exe, os.X_OK):
            raise FileNotFoundError(f"AGY_BIN is set to {env}, which is not an executable file")
        return exe
    default = HOME / ".gemini" / "bin" / "agy"
    if default.exists():
        return str(default)
    found = shutil.which("agy")
    if found:
        return found
    raise FileNotFoundError("agy not found: set AGY_BIN or install it at ~/.gemini/bin/agy")
