"""Build output stays out of the repository.

`P2.1` moved the engine and the `.gitignore` rule kept naming the old path. The
rule did not error, it simply stopped matching, and three built assets - a
bundled JS file, its CSS and an index.html - went into the commit alongside the
move. Nothing failed; the diff was 106 files and they were easy to miss among
the renames.

A stale ignore rule is silent by construction: the thing it protects against is
"a file appears that nobody meant to add", and the symptom is a file appearing
that nobody meant to add.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories whose contents are produced by a build and never committed.
GENERATED = (
    "engines/t2pbi/desktop/web",
    "apps/web/.next",
    "apps/web/node_modules",
)


def _tracked() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, cwd=ROOT, check=True
    ).stdout.split("\n")


def test_no_generated_file_is_tracked():
    offenders = [
        name
        for name in filter(None, _tracked())
        if any(name.startswith(f"{directory}/") for directory in GENERATED)
    ]
    assert offenders == [], (
        f"{offenders} are build output and are being tracked. A .gitignore rule "
        "that names a path which has since moved stops matching silently."
    )


def test_the_ignore_rules_name_paths_that_exist():
    """A rule pointing at nothing is a rule protecting nothing.

    Checked against the directories this file already knows are generated,
    rather than every line of `.gitignore` - most of those are patterns, and a
    pattern that currently matches nothing is perfectly normal.
    """
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for directory in GENERATED:
        if not (ROOT / directory).exists():
            continue  # not built here; nothing to say about it
        assert directory in ignored or any(
            part in ignored for part in (f"{Path(directory).name}/",)
        ), f"{directory} exists and is not ignored"
