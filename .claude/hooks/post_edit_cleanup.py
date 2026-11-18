"""
PostToolUse hook (Edit|Write): clean up a Python file right after Claude edits it.

  1. ruff check --fix   (unused imports, import order, pyupgrade, ...)
  2. ruff format        (consistent formatting; config in ruff.toml)

Anything ruff can't auto-fix is fed back to Claude as additionalContext so it gets fixed
in the same turn. Never blocks and never fails the tool call: if ruff is missing it just
says so once.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
SKIP_PARTS = {".venv", "venv", "__pycache__", "fixtures", ".git"}


def ruff_cmd() -> list[str]:
    venv_py = PROJECT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return [str(venv_py if venv_py.exists() else sys.executable), "-m", "ruff"]


def emit(context: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": context}}))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or (payload.get("tool_response") or {}).get("filePath")
    if not file_path:
        return
    path = Path(file_path)
    if path.suffix != ".py" or not path.exists() or SKIP_PARTS & set(path.parts):
        return
    try:
        path.resolve().relative_to(PROJECT.resolve())
    except ValueError:
        return  # outside this project

    ruff = ruff_cmd()
    run = dict(cwd=PROJECT, capture_output=True, text=True, timeout=60)
    try:
        subprocess.run([*ruff, "check", "--fix", "--quiet", str(path)], **run)
        subprocess.run([*ruff, "format", "--quiet", str(path)], **run)
        left = subprocess.run([*ruff, "check", "--output-format", "concise", "--quiet", str(path)], **run)
    except (OSError, subprocess.TimeoutExpired) as e:
        emit(f"post_edit_cleanup: could not run ruff ({e}). Install it: .venv\\Scripts\\python.exe -m pip install ruff")
        return

    if "No module named ruff" in (left.stderr or ""):
        emit("post_edit_cleanup: ruff is not installed. Run: .venv\\Scripts\\python.exe -m pip install ruff")
        return
    issues = (left.stdout or "").strip()
    if left.returncode != 0 and issues:
        rel = path.resolve().relative_to(PROJECT.resolve())
        emit(
            f"Ruff auto-fixed and formatted {rel}, but these issues need a manual fix "
            f"(re-read the file first — it was reformatted):\n{issues}"
        )


if __name__ == "__main__":
    main()
