---
description: Pull latest from git and start a clean feature branch (enforces the team's branch-per-feature rule).
---

Start a new feature working session for: $ARGUMENTS

Do this safely, step by step:

1. Check `git status`. If there are uncommitted changes, STOP and ask the user how to
   handle them — do not discard anything.
2. Switch to `main` and `git pull` the latest.
3. Create and switch to a new branch: `feature/<kebab-name-from-$ARGUMENTS>`.
4. Confirm the current branch with `git branch --show-current`.
5. Remind the user of the SDD flow: Spec → review → Technical Design → review →
   Tasks → Build → Validate, and that we commit at each milestone and push the
   branch (never commit straight to `main`).
