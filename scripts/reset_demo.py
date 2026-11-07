"""Reset the demo to its starting state, without touching Switch or the agents' workspace folders.

* Rebuilds the shared origin from ledgerly/ (no branches, no history of earlier fixes).
* Re-clones ledgerly/ inside each regional workspace (the workspace folders themselves stay: running agents
  use them as their working directory, and Windows won't delete a process's working directory).
* Refreshes the Berlin vault and reconciler, removes stray reports.
* Archives the clerk's state and ledger to .customs/archive/<timestamp>/ (credentials are kept).

Agents still remember earlier runs: clear them in chat with `!reset` in each regional room afterwards.

Usage:  python scripts/reset_demo.py [--root ~/customs-regions]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default="~/customs-regions")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if not (root / "in").is_dir() or not (root / "eu").is_dir():
        print(f"{root} has no in/ and eu/ workspaces; run scripts/setup_regions.py first")
        return 1

    origin = root / "origin" / "ledgerly.git"
    seed = root / "origin" / "seed"
    shutil.rmtree(origin, ignore_errors=True)
    shutil.rmtree(seed, ignore_errors=True)
    shutil.copytree(REPO / "ledgerly", seed, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    git("init", "-q", "-b", "main", cwd=seed)
    git("add", ".", cwd=seed)
    git("-c", "user.name=Ledgerly", "-c", "user.email=dev@ledgerly.example", "commit", "-qm", "Ledgerly 0.3.0", cwd=seed)
    git("clone", "-q", "--bare", str(seed), str(origin))
    shutil.rmtree(seed, ignore_errors=True)

    for region in ("in", "eu"):
        workspace = root / region
        shutil.rmtree(workspace / "ledgerly", ignore_errors=True)
        git("clone", "-q", str(origin), str(workspace / "ledgerly"))
        git("config", "core.fsmonitor", "false", cwd=workspace / "ledgerly")
        for stray in workspace.glob("report*.json"):
            stray.unlink()
    shutil.rmtree(root / "eu" / "vault", ignore_errors=True)
    shutil.copytree(REPO / "fixtures" / "eu-vault", root / "eu" / "vault")
    shutil.copy2(REPO / "tools" / "verify_vault.py", root / "eu" / "tools" / "verify_vault.py")

    data = REPO / ".customs"
    archived = []
    if data.is_dir():
        target = data / "archive" / datetime.now().strftime("%Y%m%d-%H%M%S")
        for name in ("state.json", "ledger.jsonl", "clerk.log"):
            if (data / name).exists():
                target.mkdir(parents=True, exist_ok=True)
                shutil.move(str(data / name), target / name)
                archived.append(name)
    print(f"origin rebuilt, workspaces re-cloned under {root}"
          + (f"; clerk {', '.join(archived)} archived" if archived else ""))
    print("Next: `!reset` in customs-in and customs-eu, then `python -m customs run`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
