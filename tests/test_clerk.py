"""The clerk process against a fake Switch server: polling, sender kinds, dedupe, outbox, restart."""

import itertools
import time

import pytest
from conftest import write_config

from customs import config as config_mod
from customs.clerk import Clerk


class FakeSwitch:
    """Just enough of the agent protocol: rooms, history, details with roles, posting."""

    def __init__(self):
        self.ids = {"customs-intake": "r-intake", "customs-in": "r-in", "customs-eu": "r-eu"}
        self.history = {rid: [] for rid in self.ids.values()}
        self.agents = {"r-intake": ["customs-clerk"], "r-in": ["customs-clerk", "in-investigator"],
                       "r-eu": ["customs-clerk", "eu-verifier"]}
        self.roles = {"r-in": [{"name": "investigator", "exclusive": True, "held_by": [{"name": "in-investigator"}]}],
                      "r-eu": [{"name": "verifier", "exclusive": True, "held_by": [{"name": "eu-verifier"}]}],
                      "r-intake": []}
        self.counter = itertools.count(1)
        self.fail_posts = 0

    def say(self, room, sender, body):
        self.history[self.ids[room]].append({"id": f"e{next(self.counter)}", "kind": "message", "sender": f"@{sender}",
                                             "sender_name": sender, "body": body, "timestamp": int(time.time() * 1000)})

    def list_rooms(self):
        return [{"name": n, "room_id": i} for n, i in self.ids.items()]

    def room_detail(self, room_id):
        return {"agent_names": self.agents[room_id], "roles": self.roles[room_id]}

    def read_context(self, room_id, since=None, limit=50):
        return {"threads": [{"root": e, "replies": []} for e in self.history[room_id][-limit:]]}

    def post(self, room_id, content):
        if self.fail_posts:
            self.fail_posts -= 1
            raise OSError("network down")
        self.say(next(n for n, i in self.ids.items() if i == room_id), "customs-clerk", content)
        return {}

    def bodies(self, room):
        return [e["body"] for e in self.history[self.ids[room]] if e["sender_name"] == "customs-clerk"]


@pytest.fixture
def setup(tmp_path):
    cfg = config_mod.load(write_config(tmp_path))
    switch = FakeSwitch()
    clerk = Clerk(cfg, switch)
    clerk.floor_ms = 0
    clerk.resolve_rooms()
    return cfg, switch, clerk


def test_open_through_the_server(setup):
    _, switch, clerk = setup
    switch.say("customs-intake", "support-lead", "@customs-clerk open C-DE-0042 totals off by a cent")
    assert clerk.poll_once() == 1
    assert switch.bodies("customs-in")[0].startswith("@investigator **TKT-0001**")
    assert clerk.poll_once() == 0  # nothing handled twice, own posts ignored


def test_sender_kind_comes_from_room_membership(setup):
    _, switch, clerk = setup
    switch.say("customs-intake", "support-lead", "@customs-clerk open C-DE-0042 x")
    clerk.poll_once()
    switch.say("customs-in", "in-investigator", "@customs-clerk status")
    switch.say("customs-in", "in-investigator", "approve H-1")  # an agent trying to sign: no such handoff yet
    clerk.poll_once()
    assert any("There is no handoff H-1" in b for b in switch.bodies("customs-in"))


def test_outbox_survives_a_crash_between_deciding_and_posting(setup, tmp_path):
    cfg, switch, clerk = setup
    switch.say("customs-intake", "support-lead", "@customs-clerk open C-DE-0042 x")
    switch.fail_posts = 1
    with pytest.raises(OSError):
        clerk.poll_once()
    assert switch.bodies("customs-in") == []  # decided, not yet announced

    restarted = Clerk(cfg, switch)  # same data_dir: state + outbox reloaded
    restarted.resolve_rooms()
    restarted.flush()
    assert len(switch.bodies("customs-in")) == 1
    assert restarted.desk.state.next_ticket == 2  # the ticket was not opened twice
    restarted.poll_once()
    assert len(switch.bodies("customs-in")) == 1


def test_duplicate_room_names_are_refused_not_guessed(tmp_path):
    cfg = config_mod.load(write_config(tmp_path))
    switch = FakeSwitch()
    original = switch.list_rooms
    switch.list_rooms = lambda: original() + [{"name": "customs-eu", "room_id": "r-eu-copy"}]
    with pytest.raises(SystemExit, match="more than one room is named customs-eu"):
        Clerk(cfg, switch).resolve_rooms()
    switch.list_rooms = lambda: original() + [{"name": "customs-eu", "room_id": "r-eu-copy", "archived": True}]
    clerk = Clerk(cfg, switch)
    clerk.resolve_rooms()
    assert clerk.room_ids["customs-eu"] == "r-eu"


def test_missing_membership_is_a_clear_error(tmp_path):
    cfg = config_mod.load(write_config(tmp_path))
    switch = FakeSwitch()
    del switch.ids["customs-eu"]
    with pytest.raises(SystemExit, match="not a member of: customs-eu"):
        Clerk(cfg, switch).resolve_rooms()
