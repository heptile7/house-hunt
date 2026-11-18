"""
Stop hook: keep README.md and CLAUDE.md in step with the code.

When Claude is about to finish a turn and the working tree has uncommitted code changes
but neither README.md nor CLAUDE.md was touched, block the stop once and ask Claude to
update them (or confirm nothing user-facing / architectural changed).

It asks only once per distinct set of code changes (fingerprint stored in
.claude/hooks/.docs_check_state), and never re-blocks while already continuing from a
stop hook, so it can't loop.
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
STATE = Path(__file__).with_name(".docs_check_state")
DOCS = {"README.md", "CLAUDE.md"}
CODE_SUFFIXES = {".py", ".js", ".html", ".css", ".bat", ".toml", ".txt"}
IGNORE_PREFIXES = ("tests/fixtures/", ".claude/")


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=PROJECT, capture_output=True, text=True, timeout=20)
    return out.stdout if out.returncode == 0 else ""


def changed_files() -> list[str]:
    files = []
    for line in git("status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].strip().strip('"')
        if " -> " in path:  # rename
            path = path.split(" -> ", 1)[1]
        files.append(path.replace("\\", "/"))
    return files


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}
    if payload.get("stop_hook_active"):
        return  # already continuing because of a stop hook: don't loop

    files = changed_files()
    if not files:
        return
    docs_touched = DOCS & set(files)
    code = [f for f in files if Path(f).suffix in CODE_SUFFIXES and not f.startswith(IGNORE_PREFIXES) and f not in DOCS]
    if not code or docs_touched == DOCS:
        return

    # Fingerprint the code diff so we ask once per set of changes, not on every turn.
    fingerprint = hashlib.sha1((git("diff", "HEAD", "--", *code) + "\n".join(sorted(code))).encode()).hexdigest()
    if STATE.exists() and STATE.read_text().strip() == fingerprint:
        return
    STATE.write_text(fingerprint)

    missing = sorted(DOCS - docs_touched)
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": (
                    f"Code changed ({', '.join(code[:8])}{' …' if len(code) > 8 else ''}) but "
                    f"{' and '.join(missing)} {'was' if len(missing) == 1 else 'were'} not updated. "
                    "Review the changes and update README.md (user-facing: features, setup, usage) and "
                    "CLAUDE.md (architecture, conventions, gotchas) where they are now stale. "
                    "If nothing documented is affected, say so briefly and stop."
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
