"""The whole custody flow, rule by rule, without a Switch server."""

from conftest import EU_VIEW, IN_VIEW, INTAKE_VIEW, handoff_block, msg

INTAKE, IN, EU = "customs-intake", "customs-in", "customs-eu"


def rooms(posts):
    return [p.room for p in posts]


def text(posts):
    return "\n".join(p.text for p in posts)


def open_ticket(desk):
    return desk.handle(msg(INTAKE, "support-lead", "@customs-clerk open C-DE-0042 invoice totals off by a cent"), INTAKE_VIEW)


def to_eu(desk, commit="abc1234"):
    open_ticket(desk)
    filed = desk.handle(msg(IN, "in-investigator", handoff_block(commit=commit)), IN_VIEW)
    pid = next(w for w in text(filed).split() if w.startswith("**H-")).strip("*")
    return desk.handle(msg(IN, "bengaluru-lead", f"approve {pid}"), IN_VIEW)


# --- opening -------------------------------------------------------------------------------------------
def test_open_sends_a_scrubbed_case_file_to_the_start_region(desk):
    posts = open_ticket(desk)
    assert rooms(posts) == [IN, INTAKE]
    case = posts[0].text
    assert case.startswith("@investigator **TKT-0001**")
    assert "BL-2026" not in case and "jana" not in case.lower() and "DE44" not in case
    assert "[INV-1]" in case and "Gerstenmalz" in case  # line items survive, identifiers don't
    assert desk.border.find_personal(case) == []
    assert "Bengaluru: 09:30 (office open)" in posts[1].text


def test_only_people_open_tickets_and_only_in_intake(desk):
    assert "Refused" in text(desk.handle(msg(INTAKE, "rogue-agent", "@customs-clerk open C-DE-0042 x", kind="agent"), INTAKE_VIEW))
    assert "opened in" in text(desk.handle(msg(IN, "support-lead", "@customs-clerk open C-DE-0042 x"), IN_VIEW))
    assert "No customer" in text(desk.handle(msg(INTAKE, "support-lead", "@customs-clerk open C-XX-1 x"), INTAKE_VIEW))


# --- filing a handoff ----------------------------------------------------------------------------------
def test_only_the_role_holder_can_hand_off(desk):
    open_ticket(desk)
    posts = desk.handle(msg(IN, "other-agent", handoff_block(), kind="agent"), IN_VIEW)
    assert "only the holder of the `investigator` role" in text(posts)
    assert "current holder: in-investigator" in text(posts)
    nobody = desk.handle(msg(IN, "in-investigator", handoff_block()), IN_VIEW.__class__(IN_VIEW.agent_names, {}))
    assert "current holder: nobody" in text(nobody)


def test_invalid_handoff_lists_errors(desk):
    open_ticket(desk)
    posts = desk.handle(msg(IN, "in-investigator", handoff_block(done=[], to=None)), IN_VIEW)
    assert '"done" needs at least one item' in text(posts) and '"to"' in text(posts)


def test_custody_route_and_commit_checks(desk):
    open_ticket(desk)
    assert "not an open ticket" in text(desk.handle(msg(IN, "in-investigator", handoff_block(ticket="TKT-0009")), IN_VIEW))
    assert "is in Bengaluru's custody" in text(desk.handle(msg(EU, "eu-verifier", handoff_block(to="in")), EU_VIEW))
    assert "not a region" in text(desk.handle(msg(IN, "in-investigator", handoff_block(to="mars")), IN_VIEW))
    assert "not on the shared origin" in text(desk.handle(msg(IN, "in-investigator", handoff_block(commit="0000000")), IN_VIEW))
    assert "releases are requested from Berlin" in text(desk.handle(msg(IN, "in-investigator", handoff_block(to="release")), IN_VIEW))


def test_valid_handoff_asks_the_source_region_to_sign_the_exact_text(desk):
    open_ticket(desk)
    [post] = desk.handle(msg(IN, "in-investigator", handoff_block()), IN_VIEW)
    assert post.room == IN and post.text.startswith("@bengaluru-lead **H-1**")
    assert "digest `" in post.text and "approve H-1" in post.text
    assert desk.state.pending["H-1"].status == "awaiting"


# --- signing --------------------------------------------------------------------------------------------
def test_agents_and_strangers_cannot_sign(desk):
    open_ticket(desk)
    desk.handle(msg(IN, "in-investigator", handoff_block()), IN_VIEW)
    assert "must be signed by a person" in text(desk.handle(msg(IN, "in-investigator", "approve H-1"), IN_VIEW))
    assert "not an approver" in text(desk.handle(msg(IN, "random-person", "approve H-1"), IN_VIEW))
    assert "signed in `customs-in`" in text(desk.handle(msg(EU, "berlin-lead", "approve H-1"), EU_VIEW))
    refusals = [e["event"] for e in desk.ledger.entries()]
    assert refusals.count("approval_refused") == 2
    assert desk.state.pending["H-1"].status == "awaiting"


def test_approval_moves_custody_and_is_single_use(desk):
    posts = to_eu(desk)
    assert rooms(posts) == [EU, IN, INTAKE]
    assert posts[0].text.startswith("@verifier **TKT-0001** is now in your custody")
    assert "Berlin: 05:00 (office closed)" in posts[1].text
    assert desk.state.tickets["TKT-0001"].custody == "eu"
    assert "already approved" in text(desk.handle(msg(IN, "bengaluru-lead", "approve H-1"), IN_VIEW))


def test_rejection_keeps_custody(desk):
    open_ticket(desk)
    desk.handle(msg(IN, "in-investigator", handoff_block()), IN_VIEW)
    posts = desk.handle(msg(IN, "bengaluru-lead", "reject H-1 add the failing test first"), IN_VIEW)
    assert "@in-investigator H-1 rejected" in text(posts) and "add the failing test first" in text(posts)
    assert desk.state.tickets["TKT-0001"].custody == "in"


# --- the border -------------------------------------------------------------------------------------------
def test_inbound_identifiers_are_reidentified_for_the_resident_region(desk):
    open_ticket(desk)  # case file assigned [INV-1].. tokens
    desk.handle(msg(IN, "in-investigator", handoff_block(next=["Re-check [INV-1] against the books"])), IN_VIEW)
    outbound = desk.state.pending["H-1"].outbound
    assert "BL-2026-0101" in outbound and "[INV-1]" not in outbound


def test_personal_data_leaving_the_eu_is_blocked_not_repaired(desk):
    to_eu(desk)
    leaky = handoff_block(to="in", commit=None, branch=None,
                          next=["Call Jana Wolff on +49 30 5557 0142 about the import"],
                          evidence=["Reconciled 38/40"])
    posts = desk.handle(msg(EU, "eu-verifier", leaky), EU_VIEW)
    body = text(posts)
    assert "Blocked at the border" in body
    assert "person name in `next[0]`" in body and "phone in `next[0]`" in body
    assert "Wolff" not in body and "5557" not in body  # the refusal itself leaks nothing
    assert not any(p.status == "awaiting" and p.source == "eu" for p in desk.state.pending.values())
    assert desk.ledger.entries()[-1]["event"] == "handoff_blocked"


def test_clean_return_handoff_is_pseudonymised_on_the_way_out(desk):
    to_eu(desk)
    back = handoff_block(to="in", commit=None, branch=None, summary="Real data: 2 invoices drop rows on import.",
                         next=["Fix parsing of thousands separators (format d.ddd,dd)"],
                         evidence=["Reconciled 38/40; failing: BL-2026-0117, BL-2026-0101"])
    [post] = desk.handle(msg(EU, "eu-verifier", back), EU_VIEW)
    assert post.text.startswith("@berlin-lead **H-2**")
    outbound = desk.state.pending["H-2"].outbound
    assert "BL-2026" not in outbound and "[INV-1]" in outbound
    delivered = desk.handle(msg(EU, "berlin-lead", "approve H-2"), EU_VIEW)
    assert delivered[0].room == IN and "BL-2026" not in delivered[0].text


# --- release ----------------------------------------------------------------------------------------------
def test_release_is_independently_verified_before_anyone_signs(desk, repo):
    to_eu(desk)
    posts = desk.handle(msg(EU, "eu-verifier", handoff_block(to="release", commit="abc1234")), EU_VIEW)
    assert "Release refused" in text(posts) and "38/40" in text(posts)
    assert repo.merged == []


def test_release_merges_exactly_the_approved_commit_and_posts_the_custody_card(desk, repo):
    to_eu(desk)
    [ask] = desk.handle(msg(EU, "eu-verifier", handoff_block(to="release", commit="fff9999")), EU_VIEW)
    assert "Independent check by the clerk" in ask.text and "40/40" in ask.text
    pid = next(w for w in ask.text.split() if w.startswith("**H-")).strip("*")
    posts = desk.handle(msg(EU, "berlin-lead", f"approve {pid}"), EU_VIEW)
    assert repo.merged == ["fff9999"]
    assert desk.state.tickets["TKT-0001"].status == "released"
    card = posts[-1]
    assert card.room == INTAKE and "Custody card TKT-0001" in card.text
    assert "| 1 | Bengaluru | Berlin | bengaluru-lead |" in card.text
    assert "| 2 | Berlin | release | berlin-lead |" in card.text
    assert "Ledger: intact" in card.text


def test_every_decision_is_on_an_intact_chain(desk):
    to_eu(desk)
    desk.handle(msg(EU, "in-investigator", "approve H-1", kind="agent"), EU_VIEW)
    events = [e["event"] for e in desk.ledger.entries()]
    assert events[:5] == ["ticket_opened", "custody_transferred", "handoff_filed", "handoff_approved", "custody_transferred"]
    assert desk.ledger.verify().ok


def test_status_and_help(desk):
    to_eu(desk)
    status = text(desk.handle(msg(INTAKE, "anyone", "@customs-clerk status"), INTAKE_VIEW))
    assert "TKT-0001" in status and "custody **Berlin**" in status
    assert "standing-order" in text(desk.handle(msg(INTAKE, "anyone", "@customs-clerk hello"), INTAKE_VIEW))
    assert desk.handle(msg(INTAKE, "anyone", "unrelated chatter"), INTAKE_VIEW) == []


def test_plain_clerk_prefix_works_without_a_mention(desk):
    posts = desk.handle(msg(INTAKE, "support-lead", "clerk open C-DE-0042 totals off by a cent"), INTAKE_VIEW)
    assert rooms(posts) == [IN, INTAKE]
    assert desk.handle(msg(INTAKE, "support-lead", "clerkship is a word, not a command"), INTAKE_VIEW) == []
    assert "TKT-0001" in text(desk.handle(msg(INTAKE, "anyone", "Clerk: status"), INTAKE_VIEW))


def test_people_are_named_by_display_name_but_ledgered_by_identity(desk):
    desk.cfg.people.update({"bengaluru-lead": "Bengaluru Lead"})
    posts = to_eu(desk)
    assert "signed out of Bengaluru by Bengaluru Lead" in posts[0].text
    assert desk.ledger.entries()[3]["actor"] == "bengaluru-lead"
