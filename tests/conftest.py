from __future__ import annotations

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from customs import config as config_mod  # noqa: E402
from customs.desk import Desk, Incoming, RoomView, State  # noqa: E402
from customs.ledger import Ledger  # noqa: E402
from customs.redact import Border  # noqa: E402
from customs.services import VaultCaseFiles  # noqa: E402

VAULT = ROOT / "fixtures" / "eu-vault"
NOON_UTC = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)  # 09:30 in Bengaluru, 05:00 in Berlin


def write_config(tmp_path: Path, **release) -> Path:
    text = (ROOT / "config" / "customs.toml").read_text(encoding="utf-8")
    text = text.replace('data_dir = "../.customs"', f'data_dir = "{(tmp_path / "data").as_posix()}"')
    text = text.replace('path = "~/customs-regions/eu/vault"', f'path = "{VAULT.as_posix()}"')
    text = text.replace('origin_repo = "~/customs-regions/origin/ledgerly.git"',
                        f'origin_repo = "{release.get("origin", tmp_path / "origin.git").as_posix()}"')
    path = tmp_path / "customs.toml"
    path.write_text(text, encoding="utf-8")
    return path


class FakeRepo:
    def __init__(self):
        self.commits = {"abc1234", "def5678", "fff9999"}
        self.passing = {"fff9999"}
        self.merged: list[str] = []

    def commit_exists(self, commit):
        return commit in self.commits

    def verify(self, commit):
        if commit in self.passing:
            return True, "Reconciled 40/40 invoices against the customer's books."
        return False, "Reconciled 38/40 invoices against the customer's books.\n- 2 x rows_dropped_on_import"

    def merge(self, commit, branch):
        self.merged.append(commit)
        return True, f"`main` fast-forwarded to `{commit}`"


@pytest.fixture
def cfg(tmp_path):
    return config_mod.load(write_config(tmp_path))


@pytest.fixture
def repo():
    return FakeRepo()


@pytest.fixture
def desk(cfg, repo):
    cases = VaultCaseFiles(VAULT)
    registries = cases.registries()
    return Desk(cfg, State(), Ledger(cfg.data_dir / "ledger.jsonl"), cases, repo,
                border_for=lambda p: Border(registries, p), now=lambda: NOON_UTC)


IN_VIEW = RoomView(frozenset({"in-investigator", "customs-clerk"}), {"investigator": ("in-investigator",)})
EU_VIEW = RoomView(frozenset({"eu-verifier", "customs-clerk"}), {"verifier": ("eu-verifier",)})
INTAKE_VIEW = RoomView(frozenset({"customs-clerk"}), {})


def msg(room, sender, body, kind=None, mid=None):
    kind = kind or ("agent" if sender.endswith(("investigator", "verifier")) else "user")
    msg.counter = getattr(msg, "counter", 0) + 1
    return Incoming(room, mid or f"m{msg.counter}", sender, kind, body)


def handoff_block(**fields) -> str:
    import json

    data = {
        "ticket": "TKT-0001",
        "to": "eu",
        "summary": "Totals used binary floats; switched to Decimal with half-up rounding.",
        "done": ["Reproduced the cent differences from the case file"],
        "next": ["Reconcile against the customer's real invoices"],
        "evidence": ["pytest: 9 passed"],
        "branch": "fix/tkt-0001",
        "commit": "abc1234",
    }
    data.update(fields)
    data = {k: v for k, v in data.items() if v is not None}
    return "Handing over.\n```customs-handoff\n" + json.dumps(data, indent=2) + "\n```"


@pytest.fixture
def fresh_vault(tmp_path):
    target = tmp_path / "vault"
    shutil.copytree(VAULT, target)
    return target
