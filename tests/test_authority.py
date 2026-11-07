"""Authority sleeps: off-duty awareness, standing orders, briefings, and the demo clock."""

import pytest
from conftest import EU_VIEW, IN_VIEW, INTAKE_VIEW, NOON_UTC, VAULT, FakeRepo, handoff_block, msg, write_config

from customs import config as config_mod
from customs.desk import Desk, State
from customs.ledger import Ledger
from customs.redact import Border
from customs.services import VaultCaseFiles

INTAKE, IN, EU = "customs-intake", "customs-in", "customs-eu"


@pytest.fixture
def desk(tmp_path):
    cfg = config_mod.load(write_config(tmp_path, time_travel=True))
    cases = VaultCaseFiles(VAULT)
    registries = cases.registries()
    d = Desk(cfg, State(), Ledger(cfg.data_dir / "ledger.jsonl"), cases, FakeRepo(),
             border_for=lambda p: Border(registries, p), now=lambda: NOON_UTC)  # wall clock: 09:30 IST / 05:00 CET
    d.tick()
    return d


def say(desk, room, who, body, view=None):
    view = view or {IN: IN_VIEW, EU: EU_VIEW, INTAKE: INTAKE_VIEW}[room]
    return "\n".join(p.text for p in desk.handle(msg(room, who, body), view))


def at(desk, region, hhmm):
    return say(desk, INTAKE, "support-lead", f"@customs-clerk time {region} {hhmm}")


def ticket_in_berlin(desk):
    """Daytime in both offices: open a ticket and hand it to Berlin."""
    at(desk, "eu", "11:00")  # 15:30 in Bengaluru: both open
    say(desk, INTAKE, "support-lead", "@customs-clerk open C-DE-0042 totals off by a cent")
    say(desk, IN, "in-investigator", handoff_block())
    say(desk, IN, "bengaluru-lead", "approve H-1")
    assert desk.state.tickets["TKT-0001"].custody == "eu"


# --- off duty -----------------------------------------------------------------------------------------
def test_requests_to_a_closed_office_say_when_its_people_are_back(desk):
    ticket_in_berlin(desk)
    at(desk, "eu", "20:00")
    text = say(desk, EU, "eu-verifier", handoff_block(to="release", commit="fff9999"))
    assert "Berlin is off duty" in text and "opens at 09:00 local, in 13h 00m" in text
    assert "don't wait idle" in text
    assert desk.state.pending["H-2"].status == "awaiting"


# --- standing orders ----------------------------------------------------------------------------------
def test_only_that_regions_approver_can_leave_a_standing_order(desk):
    ticket_in_berlin(desk)
    assert "Refused" in say(desk, EU, "eu-verifier", "@customs-clerk standing-order release TKT-0001 until 09:00")
    assert "Refused" in say(desk, EU, "bengaluru-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    assert "Releases are signed by Berlin" in say(desk, IN, "bengaluru-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    assert "not an open ticket" in say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0042 until 09:00")
    assert desk.state.orders == {}


def test_overnight_release_under_a_standing_order(desk):
    ticket_in_berlin(desk)
    at(desk, "eu", "17:55")
    text = say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    assert "SO-1" in text and "only if" in text and "once, until 09:00 Berlin time" in text

    at(desk, "eu", "04:10")  # Berlin asleep; agents are not
    text = say(desk, EU, "eu-verifier", handoff_block(to="release", commit="fff9999"))
    assert "berlin-lead** left standing order **SO-1" in text
    assert "TKT-0001 released" in text
    assert desk.repo.merged == ["fff9999"]
    assert desk.state.orders["SO-1"].status == "used"
    card = desk.state.tickets["TKT-0001"].history[-1]
    assert card["signed_by"] == "berlin-lead (standing order SO-1)"
    events = [e["event"] for e in desk.ledger.entries()]
    assert "standing_order_used" in events and events[-1] == "released"
    assert desk.ledger.verify().ok


def test_a_standing_order_never_signs_a_release_that_fails_verification(desk):
    ticket_in_berlin(desk)
    at(desk, "eu", "17:55")
    say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    at(desk, "eu", "04:10")
    text = say(desk, EU, "eu-verifier", handoff_block(to="release", commit="abc1234"))
    assert "Release refused" in text and desk.repo.merged == []
    assert desk.state.orders["SO-1"].status == "active"  # still there for a passing commit


def test_expired_and_revoked_orders_do_nothing(desk):
    ticket_in_berlin(desk)
    at(desk, "eu", "17:55")
    say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 23:00")
    at(desk, "eu", "23:30")
    assert desk.state.orders["SO-1"].status == "expired"
    text = say(desk, EU, "eu-verifier", handoff_block(to="release", commit="fff9999"))
    assert "needs your signature" in text and desk.repo.merged == []

    say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    assert "SO-2 revoked" in say(desk, EU, "berlin-lead", "@customs-clerk revoke SO-2")
    assert desk.state.orders["SO-2"].status == "revoked"


def test_a_handoff_standing_order_lets_work_leave_while_its_lead_sleeps(desk):
    at(desk, "in", "16:00")
    say(desk, INTAKE, "support-lead", "@customs-clerk open C-DE-0042 totals off by a cent")
    say(desk, IN, "bengaluru-lead", "@customs-clerk standing-order handoff TKT-0001 until 09:00")
    at(desk, "in", "23:40")  # Bengaluru asleep, Berlin 19:10, the agent finishes late
    text = say(desk, IN, "in-investigator", handoff_block())
    assert "left standing order **SO-1**" in text
    assert desk.state.tickets["TKT-0001"].custody == "eu"


def test_standing_orders_are_bounded(desk):
    ticket_in_berlin(desk)
    assert "Usage" in say(desk, EU, "berlin-lead", "@customs-clerk standing-order merge everything forever")
    assert "Usage" in say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 27:00")


# --- briefings ----------------------------------------------------------------------------------------
def test_closing_note_suggests_a_standing_order_and_morning_briefing_reports_the_night(desk):
    ticket_in_berlin(desk)
    closing = at(desk, "eu", "18:05")
    assert "Berlin is closing" in closing and "standing-order release TKT-0001 until 09:00" in closing
    say(desk, EU, "berlin-lead", "@customs-clerk standing-order release TKT-0001 until 09:00")
    at(desk, "eu", "03:00")
    say(desk, EU, "eu-verifier", handoff_block(to="release", commit="fff9999"))
    morning = at(desk, "eu", "09:01")
    assert "Good morning, Berlin" in morning
    assert "signed under your standing order SO-1" in morning
    assert "TKT-0001 was released" in morning


# --- demo clock ---------------------------------------------------------------------------------------
def test_the_demo_clock_is_for_people_only_and_is_ledgered(desk):
    assert "Only a person" in say(desk, IN, "in-investigator", "@customs-clerk time +8h")
    assert "Berlin: 18:05" in at(desk, "eu", "18:05")
    assert desk.ledger.entries()[-1]["event"] == "clock_moved"
    assert "Bengaluru" in say(desk, INTAKE, "support-lead", "@customs-clerk time reset")


def test_the_demo_clock_is_off_unless_configured(tmp_path):
    cfg = config_mod.load(write_config(tmp_path, time_travel=False))
    cases = VaultCaseFiles(VAULT)
    d = Desk(cfg, State(), Ledger(cfg.data_dir / "l.jsonl"), cases, FakeRepo(),
             border_for=lambda p: Border(cases.registries(), p), now=lambda: NOON_UTC)
    assert "Time travel is off" in "\n".join(p.text for p in d.handle(msg(INTAKE, "x", "@customs-clerk time +8h"), INTAKE_VIEW))


def test_a_standing_order_waits_while_its_owner_is_at_their_desk(desk):
    ticket_in_berlin(desk)  # Berlin 11:00, office open
    say(desk, EU, "berlin-lead", "clerk standing-order release TKT-0001 until 09:00")
    text = say(desk, EU, "eu-verifier", handoff_block(to="release", commit="fff9999"))
    assert "needs your signature" in text and desk.repo.merged == []
    assert desk.state.orders["SO-1"].status == "active"  # kept for tonight
