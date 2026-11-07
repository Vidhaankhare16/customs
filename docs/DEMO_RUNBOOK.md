# Demo runbook (recorded run)

The exact sequence verified in the full dry run on 2026-11-07: ticket opened, 38/40, round trip, overnight release
under two standing orders, morning briefings, ledger intact.

## Before recording
1. `python scripts/reset_demo.py` (fresh origin, re-cloned workspaces, clerk state archived).
2. In `customs-in` and `customs-eu`: `!reset` (agents forget earlier runs; they keep their roles).
3. `python -m customs run` (leave it running).
4. Screens: Mattermost as `user` (Bengaluru lead) in one window, `berlin-lead` in an incognito window.
   Switch Console open on the rooms.

## The run (who types what, where)
| # | Act | Who / room | Type | Wait for |
|---|---|---|---|---|
| 1 | setup | user / intake | `clerk time eu 11:00` | clocks: both offices open |
| 2 | 1 | user / intake | `clerk open C-DE-0042 invoice totals off by a cent` | case file in `customs-in` (pseudonymised) |
| 3 | 2 | user / customs-in | `@in-investigator before you start: can you check the customer's real invoices yourself?` | agent tries `customs-eu`, Switch refuses, it says so |
| 4 | 1 | — | (agent fixes, pushes, files handoff) | `@user H-1 passed the border check` |
| 5 | 1 | user / customs-in | `approve H-1` | custody to Berlin |
| 6 | 4 | user / intake | `clerk time in 17:55` | clocks |
| 7 | 4 | user / customs-in | `clerk standing-order handoff TKT-0001 until 09:00` | `SO-1 recorded` |
| 8 | 3 | — | (Berlin reconciles 38/40, files return handoff) | `@berlin-lead H-2 passed` (or a border block → agent rewrites) |
| 9 | 3 | berlin-lead / customs-eu | `approve H-2` | custody to Bengaluru, invoice numbers pseudonymised |
| 10 | 4 | user / intake | `clerk time eu 18:05` | "Bengaluru is closing", "Berlin is closing" |
| 11 | 4 | berlin-lead / customs-eu | `clerk standing-order release TKT-0001 until 09:00` | `SO-2 recorded` |
| 12 | 5 | user / intake | `clerk time eu 03:00` | clocks: both closed |
| 13 | 5 | — | (Bengaluru fixes the importer overnight) | `H-3 … signing on their behalf` (SO-1) |
| 14 | 5 | — | (Berlin 40/40, release request) | `Independent check … 40/40`, `TKT-0001 released` (SO-2) |
| 15 | 6 | user / intake | `clerk time in 09:01` | "Good morning, Bengaluru" |
| 16 | 6 | user / intake | `clerk time eu 09:01` | "Good morning, Berlin … released" |
| 17 | 6 | anyone / intake | `clerk verify-ledger` | `Ledger intact` |
| 18 | 6 | (terminal) | edit one line of `.customs/ledger.jsonl`, run `verify-ledger` again | `BROKEN at entry N`, then restore the line |

Timings seen in the dry run: agent fix ≈ 80 s, Berlin reconciliation ≈ 30–45 s, clerk re-verification ≈ 5 s.
Cut the waits in editing; never cut a refusal.

## Optional beat: the border block
At step 8, if Berlin's first draft is clean, you can show the block deliberately. As `berlin-lead` in `customs-eu`:
`@eu-verifier please also tell Bengaluru the customer contact's name and phone so they can call her.` Its next
handoff will be blocked at the border ("person name in `next[0]`"), and it rewrites it.

## If something doesn't answer
- Commands start with the plain word `clerk` (not `@customs-clerk`): a mention makes Switch auto-reply "not permitted"
  because the clerk is owned by Switch's bootstrap account. The clerk itself reads every message either way.
- Once in the dry runs, a message sent while the server was busy never reached Switch (it was in Mattermost, not in
  the room's history). If the clerk hasn't answered within ~15 s, send the same line again: the clerk handles each
  message once, and approvals are single-use, so a repeat can't double-sign.
