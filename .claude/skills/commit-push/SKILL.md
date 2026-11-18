---
name: commit-push
description: Commit the current changes in this repo and push them to GitHub (heptile7/house-hunt). Use whenever the user asks to commit, push, "commit and push", "ship it", "save to GitHub/the repo", "upload the changes", or "sync with GitHub", or invokes /commit-push. Runs lint and tests, checks for secrets and stale docs, writes the commit message, commits and pushes.
---

# Commit & push (house_hunting)

Remote: `origin` → https://github.com/heptile7/house-hunt.git, branch `main`. This is a single-developer repo, so committing straight to `main` is the normal workflow here.

Run every command from the project root `D:\GPT\house_hunting`.

## 1. Look at what's changing
```bash
git status --short
git diff --stat HEAD
```
- If there is nothing to commit, say so and stop. If `main` is ahead of `origin/main`, offer to push those commits instead.
- Read the diff (`git diff HEAD`; for long diffs use `--stat`, then the files that matter) so the commit message describes what actually changed.

## 2. Safety checks (stop and tell the user if any of these fail)
- **Secrets / local data must never be committed:** `.env`, `*.db`, `*.db-journal`, `.claude/settings.local.json`, `.claude/hooks/.docs_check_state`, `.venv/`. They are in `.gitignore`. Also check `git status --short` for any of these, or for files that look like credentials (keys, tokens, `*.pem`). If one is tracked or staged, stop and ask.
- **Lint:** `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m ruff format --check .`. If they fail, run `ruff check --fix .` and `ruff format .`, then re-check. Anything still failing has to be fixed or reported. Don't commit around it.
- **Tests:** `.venv/Scripts/python.exe -m pytest -q -p no:anyio`. If tests fail, don't commit. Show the failures and ask whether to fix them first.
- **Docs:** if behaviour, setup, sources, API or conventions changed, check that `README.md` (user-facing) and `CLAUDE.md` (architecture/conventions) reflect it. Update them before committing if they're stale.

## 3. Commit
- Stage explicitly: `git add -A`, then re-check `git status --short`. Every staged file should belong to this change.
- Message:
  - Subject in the imperative, at most 72 chars, describing the main change (e.g. `Add SquareYards and CommonFloor sources and locality filter`).
  - Blank line, then a short body: a few `-` bullets covering *what* and *why*, and any notable fix.
  - End with the attribution trailer the session's system reminder specifies for commits (currently `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`). If the user or CLAUDE.md says otherwise, follow that instead.
- On Windows/PowerShell, pass a multi-line message with a single-quoted here-string (`git commit -m @'...'@`). In Bash, use `git commit -F -` with a heredoc.
- Never use `--no-verify`, `--amend` on pushed commits, or `-c commit.gpgsign=false` unless the user asks.

## 4. Push
```bash
git push            # upstream is already set: main -> origin/main
```
- **Rejected (non-fast-forward):** run `git pull --rebase` and push again. If the rebase hits conflicts, stop, run `git rebase --abort`, and tell the user. Don't resolve conflicts silently.
- **Auth failure:** git signs in as **heptile7** through Git Credential Manager. Ask the user to run `! git push` themselves so the sign-in window can appear.
- **Never** force-push (`--force`, `--force-with-lease`) unless the user explicitly asks.

## 5. Report
Reply in a few lines:
- the commit hash and subject (`git log --oneline -1`)
- what was included (one line per area)
- check results (lint ✓, N tests passed)
- that it was pushed: https://github.com/heptile7/house-hunt/commit/<hash>
