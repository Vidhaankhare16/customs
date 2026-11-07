"""GitOrigin against real git and the real reconciliation tool: the release path end to end."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import ROOT, VAULT

from customs.services import GitOrigin

VERIFY = ("{python}", str(ROOT / "tools" / "verify_vault.py"), "--repo", "{checkout}", "--vault", "{vault}")


def git(cwd, *args):
    return subprocess.run(["git", "-c", "core.fsmonitor=false", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def edit(path: Path, old: str, new: str):
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {path}"
    path.write_text(text.replace(old, new), encoding="utf-8")


PARTIAL_FIX = [
    ("ledgerly/invoice.py", "from dataclasses import dataclass, field",
     'from dataclasses import dataclass, field\nfrom decimal import ROUND_HALF_UP, Decimal\n\nCENT = Decimal("0.01")\n\n\n'
     "def _cents(value):\n    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)"),
    ("ledgerly/invoice.py", "return round(line.quantity * line.unit_price, 2)",
     "return _cents(Decimal(str(line.quantity)) * Decimal(str(line.unit_price)))"),
    ("ledgerly/invoice.py", "return round(line_net(line) * line.vat_rate, 2)",
     "return _cents(line_net(line) * Decimal(str(line.vat_rate)))"),
    ("ledgerly/invoice.py", 'return {"net": round(net, 2), "vat": round(vat, 2), "gross": round(net + vat, 2)}',
     'return {"net": _cents(net), "vat": _cents(vat), "gross": _cents(net + vat)}'),
]
FULL_FIX = [
    ("ledgerly/importer.py", 'return float(text.strip().replace(",", "."))',
     'from decimal import Decimal\n\n    return Decimal(text.strip().replace(".", "").replace(",", "."))'),
    ("ledgerly/importer.py", "except ValueError:\n                continue  # TODO: malformed rows from old exports",
     "except ValueError:\n                raise"),
]


@pytest.fixture
def origin(tmp_path):
    work = tmp_path / "work"
    shutil.copytree(ROOT / "ledgerly", work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    git(work, "init", "-q", "-b", "main")
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ledgerly 0.3.0")
    bare = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    git(work, "remote", "add", "origin", str(bare))

    def commit(changes, branch, message):
        git(work, "checkout", "-q", "-B", branch)
        for rel, old, new in changes:
            edit(work / rel, old, new)
        git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", message)
        git(work, "push", "-q", "origin", branch)
        return git(work, "rev-parse", "--short", "HEAD")

    partial = commit(PARTIAL_FIX, "fix/tkt-0001", "decimal rounding")
    full = commit(FULL_FIX, "fix/tkt-0001", "parse German thousands separators")
    return GitOrigin(bare, VAULT, VERIFY), partial, full, bare


def test_commit_exists(origin):
    repo, partial, full, _ = origin
    assert repo.commit_exists(partial) and repo.commit_exists(full)
    assert not repo.commit_exists("0000000")


def test_independent_verification_tells_partial_from_full_fix(origin):
    repo, partial, full, _ = origin
    ok, summary = repo.verify(partial)
    assert not ok and "38/40" in summary and "d.ddd,dd" in summary
    ok, summary = repo.verify(full)
    assert ok and "40/40" in summary


def test_main_is_buggy_before_release(origin):
    repo, *_ , bare = origin
    ok, summary = repo.verify("main")
    assert not ok and re.search(r"Reconciled 2\d/40", summary)


def test_merge_fast_forwards_exactly_the_commit(origin):
    repo, partial, full, bare = origin
    ok, detail = repo.merge(full, "fix/tkt-0001")
    assert ok, detail
    assert git(bare, "rev-parse", "main").startswith(repo.resolve(full)[:10])


def test_merge_refuses_a_non_fast_forward(origin, tmp_path):
    repo, partial, full, bare = origin
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(bare), str(other))
    (other / "NOTES.md").write_text("someone else shipped first\n", encoding="utf-8")
    git(other, "add", ".")
    git(other, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "unrelated")
    git(other, "push", "-q", "origin", "main")
    ok, detail = repo.merge(full, "fix/tkt-0001")
    assert not ok and "not a fast-forward" in detail
