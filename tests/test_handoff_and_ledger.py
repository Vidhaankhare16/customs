import json

from conftest import handoff_block

from customs import handoff
from customs.ledger import Ledger


def test_valid_handoff_parses():
    parsed, errors = handoff.parse(handoff_block())
    assert errors == []
    assert parsed.ticket == "TKT-0001" and parsed.commit == "abc1234"


def test_every_problem_is_reported_at_once():
    body = "```customs-handoff\n" + json.dumps({"ticket": "T1", "to": "", "done": "x", "evil": 1, "commit": "XYZ"}) + "\n```"
    parsed, errors = handoff.parse(body)
    assert parsed is None
    text = " ".join(errors)
    for expected in ("unknown fields: evil", "TKT-0001", '"to"', '"summary"', '"done"', '"next"', "commit"):
        assert expected in text


def test_missing_block_and_bad_json():
    assert handoff.parse("just chatting")[1] == ["no ```customs-handoff block found"]
    assert "not valid JSON" in handoff.parse("```customs-handoff\n{nope\n```")[1][0]


def test_branch_and_commit_go_together():
    _, errors = handoff.parse(handoff_block(commit=None))
    assert any("go together" in e for e in errors)


def test_ledger_chain_detects_tampering(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i in range(5):
        ledger.append("event", "TKT-0001", "someone", "in", n=i)
    assert ledger.verify().ok

    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])
    entry["actor"] = "someone-else"
    lines[2] = json.dumps(entry)
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = ledger.verify()
    assert not result.ok and result.broken_at == 3 and result.reason == "entry contents changed"


def test_ledger_detects_deleted_entry(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    for i in range(4):
        ledger.append("event", None, "a", n=i)
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not ledger.verify().ok
