# Customs: demo video script

> Planning script. The final narration (AI voice, 2:54) was produced with demo-video-kit, recording Mattermost in the
> browser; the beats are the same.

**Length:** about 3:00 (≈ 450 spoken words at a calm pace).
**Shape:** stakes, then two bad options, then one idea, then one real run with four "wow" beats (the wall, the
border, 3 AM, the morning), then why Switch, then the tagline.
**Rule while editing:** cut every wait; never cut a refusal.

Filmed with demo-video-kit: Mattermost in the browser for the live run, short Switch Console shots for the setup.
The run follows `docs/DEMO_RUNBOOK.md` step by step.

---

## 1. Hook: the stakes (0:00–0:15)

| Narration | On screen |
|---|---|
| In 2023, Meta was fined one point two billion euros for moving Europeans' data to the United States. | Title card, black: "€1.2 billion" fades in, then "for moving EU data out of the EU". |
| Every global company now works with that border. And AI agents are about to cross it thousands of times a day. | Slow zoom onto a world map with two pins: Bengaluru and Berlin, 4.5 h apart. |

## 2. The problem (0:15–0:40)

| Narration | On screen |
|---|---|
| Say your engineers are in Bengaluru, and your customers' data lives in Berlin. Your agents can work all night. | Two clocks side by side: Bengaluru 15:30, Berlin 11:00. |
| But they hit two walls. The data isn't allowed to leave the EU. And the person allowed to say "yes, ship it" is asleep. | Wall 1: "Access is regional". Wall 2: "Authority sleeps". |
| So teams pick one of two bad options: give the agent everything, or make it wait until morning. | Two cards: "Give it all access + auto-approve" crossed out in red; "Human in every loop: wait 8 hours" crossed out in red. |

## 3. The idea (0:40–0:58)

| Narration | On screen |
|---|---|
| We built Customs, on Switch. Each region's agents live in their own room. Work crosses between rooms. Data doesn't. | Switch Console: the "Customs desk" group, with customs-intake, customs-in and customs-eu. |
| At the border sits a clerk, written in code, not a prompt. It decides what crosses, who has to sign, and what ships. | Mattermost sidebar with the three channels. Callout on `customs-clerk`: "Not an AI. The only member of every room." |

## 4. Act 1: a ticket arrives (0:58–1:15)

| Narration | On screen |
|---|---|
| Here's one real ticket. A German brewery says our invoice totals are off by a cent, and their auditor wants it fixed. | `customs-intake`: type `clerk open C-DE-0042 invoice totals off by a cent`. |
| The clerk hands Bengaluru a case file with names, phone numbers, emails and invoice numbers already masked. | `customs-in`: the case file. Spotlight on `[PERSON_NAME]`, `[PHONE]`, `[INV-1]`. |

## 5. Act 2: the wall (1:15–1:27)

| Narration | On screen |
|---|---|
| Can the Bengaluru agent just look at the real invoices? It tries, and Switch refuses: it isn't a member of the Berlin room. No prompt said no. The server did. | Ask `@in-investigator` to check the real invoices. Its reply quoting Switch's refusal. Banner: "Enforced by Switch, not a prompt". |

## 6. Act 3: the crossing (1:27–1:40)

| Narration | On screen |
|---|---|
| It fixes the rounding, pushes the code, and hands the ticket over. The Bengaluru lead signs the exact text that will cross. | The `customs-handoff` block, then the clerk's "H-1 passed the border check" with its digest. Type `approve H-1`. |
| Now the ticket is Berlin's, and only inside Berlin do the invoice numbers turn back into real ones. | `customs-eu`: the handoff arrives with `BL-2026-0101`. Callout: "Re-identified only inside the EU". |

## 7. Act 4: real data finds what samples can't (1:40–2:00)

| Narration | On screen |
|---|---|
| Berlin checks the fix against the customer's real records. Thirty-eight out of forty. | Berlin's reconciliation: "Reconciled 38/40". Zoom on the number. |
| The customer's system writes big amounts German style, with a dot and a comma, and our importer was silently dropping those rows. Bengaluru could never have seen that. | Callout on "unit_price=d.ddd,dd (formats only, no values)". |
| Berlin sends back the pattern, never the values, and the clerk masks the invoice numbers on the way out. | `customs-in`: the return handoff with `[INV-4]`, `[INV-5]`. |

## 8. Act 5: night falls (2:00–2:15)

| Narration | On screen |
|---|---|
| Six in the evening in Berlin. Before logging off, the Berlin lead leaves a standing order: release this ticket only if the clerk's own check passes. Once. Until nine. | "Berlin is closing" note. Type `clerk standing-order release TKT-0001 until 09:00`. The clerk restates its limits. Clocks dim to night. |

## 9. Act 6: 3 AM, nobody awake (2:15–2:33)

| Narration | On screen |
|---|---|
| Three in the morning. Bengaluru's agent fixes the importer. Berlin's agent reconciles: forty out of forty. | Clock: Berlin 03:00. "H-3 … signed under standing order SO-1". "Reconciled 40/40". |
| The clerk doesn't take its word for it. It re-runs the check on that exact commit, signs under the standing order, and merges exactly that commit. | "Independent check by the clerk … 40/40", then "TKT-0001 released. main fast-forwarded to 059e92e". |

## 10. Act 7: morning, and proof (2:33–2:48)

| Narration | On screen |
|---|---|
| At nine, the Berlin lead wakes up to this. Fixed, verified and released, six hours before anyone was awake to approve it. | "Good morning, Berlin. While you were away: … TKT-0001 was released". |
| Every crossing, who signed it, and how. Personal data that left the EU: none. And the log is tamper-evident: change one line, and it says exactly where. | Custody card, then `clerk verify-ledger`: "intact". Edit one ledger line: "BROKEN at entry 9". |

## 11. Why Switch, and the close (2:48–3:05)

| Narration | On screen |
|---|---|
| Without Switch, these agents couldn't reach each other, couldn't be kept apart, and nobody would know who owns the ticket. With Switch, the whole desk is one template. | Switch Console: the template's "What it creates" view. |
| Swap the rules, and it's a law firm keeping client files apart, a hospital keeping patient records in-house, or a bank keeping Indian payment data in India. | Three quick cards. |
| Customs. Work crosses borders. Data doesn't. | End card: "Customs", the tagline, the repo URL, "Built on Switch". |

---

## Notes for the shoot
- **Every number on screen is real**, from the run being filmed: 38/40, 40/40, the commit, the digests, the times.
  If a take produces different numbers, change the narration to match rather than editing the screen.
- **The Meta fine:** the Irish Data Protection Commission fined Meta €1.2 billion in May 2023 over EU→US data
  transfers. Keep the wording to exactly what happened.
- **Optional beat (if time allows):** the border block. Berlin's draft names the customer contact, and the clerk
  answers "Blocked at the border: person name in `next[0]`". About 8 s. It fits after Act 4's first line.
- **The voice:** calm and confident, and slower on the four wow lines: "The server did." "Thirty-eight out of
  forty." "Nobody awake." "Six hours before anyone was awake to approve it."
