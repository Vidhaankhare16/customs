"""Create the regional workspaces the Customs agents run in.

    <root>/origin/ledgerly.git   shared repository (stands in for GitHub)
    <root>/in/                   Bengaluru agent's working directory: a clone, and nothing customer-related
    <root>/eu/                   Berlin agent's working directory: a clone, the customer vault, the reconciler

On one machine, the separation between in/ and eu/ is a guard rail: the Bengaluru workspace gets Claude Code
deny rules for everything under eu/. The boundary that holds no matter what is Switch's: the Bengaluru agent
is not a member of the EU room, so Switch refuses to show it anything said or shared there. In production the
two workspaces are different machines (Switch "remote hosts").

Usage:  python scripts/setup_regions.py [--root ~/customs-regions] [--force]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

IN_NOTES = """# Bengaluru workspace (Customs demo)

You are the Bengaluru engineering agent for Ledgerly. `ledgerly/` is your clone of the shared repository
(remote `origin`). Customer records are EU-resident: they are not in this workspace, and you must not try to
reach them. You work from the pseudonymised case files the Customs clerk posts in your Switch room.
"""

EU_NOTES = """# Berlin workspace (Customs demo)

You are the Berlin verification agent for Ledgerly. This workspace is inside the EU boundary:

- `ledgerly/` is your clone of the shared repository (remote `origin`).
- `vault/` holds the customer's real records. They contain personal data. Never paste vault rows, report
  files or personal details into any chat. Describe patterns, not people or values.
- `tools/verify_vault.py` reconciles a Ledgerly checkout against the vault:
  `python tools/verify_vault.py --repo ledgerly --vault vault --report report.json`
  Its stdout summary is written to be shareable; `report.json` is not.
"""


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True, text=True)


def claude_settings(eu: Path) -> dict:
    posix = eu.resolve().as_posix()
    if ":" in posix:  # C:/Users/... -> //c/Users/... (Claude Code's absolute-path rule form on Windows)
        drive, rest = posix.split(":", 1)
        absolute = f"//{drive.lower()}{rest}"
    else:
        absolute = "/" + posix
    rules = []
    for target in (f"{absolute}/**", "../eu/**"):
        rules += [f"Read({target})", f"Edit({target})", f"Write({target})"]
    return {"permissions": {"deny": rules}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default="~/customs-regions")
    parser.add_argument("--force", action="store_true", help="delete and recreate an existing root")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if root.exists():
        if not args.force:
            print(f"{root} already exists. Re-run with --force to recreate it (this deletes it).")
            return 1
        shutil.rmtree(root)

    origin, work_in, work_eu = root / "origin" / "ledgerly.git", root / "in", root / "eu"
    seed = root / "origin" / "seed"
    shutil.copytree(REPO / "ledgerly", seed, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    run("git", "init", "-q", "-b", "main", cwd=seed)
    run("git", "add", ".", cwd=seed)
    run("git", "-c", "user.name=Ledgerly", "-c", "user.email=dev@ledgerly.example", "commit", "-qm",
        "Ledgerly 0.3.0", cwd=seed)
    run("git", "clone", "-q", "--bare", str(seed), str(origin))
    shutil.rmtree(seed, ignore_errors=True)

    for workspace, notes in ((work_in, IN_NOTES), (work_eu, EU_NOTES)):
        workspace.mkdir(parents=True)
        run("git", "clone", "-q", str(origin), str(workspace / "ledgerly"))
        (workspace / "CLAUDE.md").write_text(notes, encoding="utf-8")
        (workspace / "AGENTS.md").write_text(notes, encoding="utf-8")  # same notes for Codex/OpenCode

    shutil.copytree(REPO / "fixtures" / "eu-vault", work_eu / "vault")
    (work_eu / "tools").mkdir()
    shutil.copy2(REPO / "tools" / "verify_vault.py", work_eu / "tools" / "verify_vault.py")

    (work_in / ".claude").mkdir()
    (work_in / ".claude" / "settings.json").write_text(json.dumps(claude_settings(work_eu), indent=2) + "\n",
                                                        encoding="utf-8")

    print(f"""Regional workspaces ready under {root}

  origin   {origin}
  in       {work_in}      (Bengaluru agent's working directory)
  eu       {work_eu}      (Berlin agent's working directory, holds the vault)

config/customs.toml expects the vault at ~/customs-regions/eu/vault and origin at
~/customs-regions/origin/ledgerly.git. If you used another --root, update those two paths.
Next: deploy switch/customs.template.yaml from Switch Console (see README).""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
