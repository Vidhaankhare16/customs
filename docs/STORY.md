# The Customs story: from the general idea to the full demo

This is the narrative spine for the README, the demo video and the blog. It starts with the general problem,
then adds one idea per act. Each act's demo beat stands on its own.

---

## Act 0: The general problem (no product yet)

AI agents have become teammates. But global organisations have two kinds of border that agents either ignore
or stop at:

1. **Authority sleeps.** An agent can work all night, but the person who must approve a release, a customer
   reply or a production change is offline. The work piles up waiting for a "yes", and by morning the time
   difference has cost a day.
2. **Access is regional.** Data residency rules (GDPR in the EU, RBI localisation in India, client
   confidentiality everywhere) mean an EU customer's data may only be handled by people and systems in the EU.
   A Bengaluru engineer, and an agent working with that engineer's access, is not allowed to see it, however
   capable it is.

Teams usually fail in one of two directions. Either they **give the agent everything** (all access, and
"auto-approve" so nobody has to wake up), or they **keep humans in every loop** and the agent waits all night.

**The question:** how do you let AI work keep moving around the clock and across regions, while every
signature and every data border still holds?

## Act 0.5: The general solution

> **Each region's agents live in their own room. Work, not data, crosses between rooms through a border
> enforced in code. Authority crosses time zones as a bounded, expiring delegation, never as a blank cheque.**

| Concept | On Switch |
|---|---|
| A region (jurisdiction) | a **room**: membership is enforced by the server |
| Who owns the task right now | an **exclusive role** in that room (one holder at a time) |
| The border | the **Customs clerk**: a custom agent, the only member of every room. Deterministic, not an AI. |
| A crossing | a structured handoff, a person's signature on the exact text, a hash-chained ledger entry |
| Authority while asleep | a **standing order**: "release TKT-0001 only if your own check passes, once, until 09:00" |
| The whole setup | one **template** |

Customs is general: regions, routes, approvers, office hours and what counts as protected data are
configuration. The rest is **one example**: an EU customer's bug, a team in Bengaluru and a team in Berlin,
4.5 hours apart.

---

## Act 1: A signed crossing (daytime: both offices open)

*New idea: custody and a signature.*

Berlin 11:00, Bengaluru 15:30. A ticket is opened in intake, and the clerk puts it in **Bengaluru's custody**.
The Bengaluru agent fixes the rounding bug and posts a handoff (summary, done, next, evidence, commit). The
clerk asks the **Bengaluru lead** to sign *this exact text* (`approve H-1`). Custody moves to Berlin.

**Demo beat (30 s).** Handoff, signature, custody moves.

## Act 2: The wall (access)

*New idea: a region holds data the other may not see.*

Someone asks the Bengaluru agent to "just check the customer's real invoices". It tries to read the Berlin
room, and **Switch refuses**: it isn't a member. No prompt said "don't"; the server did.

**Demo beat (20 s).** The refusal, verbatim.

## Act 3: The border check (access)

*New idea: what crosses is inspected.*

Bengaluru only ever saw a case file with `[INV-1]` instead of invoice numbers, and no names or emails. In
Berlin, the clerk turns `[INV-1]` back into the real number. Berlin reconciles against the real records and
gets **38/40**: the customer's ERP writes `1.234,50`, and the importer silently drops those rows. The Berlin
agent's first draft back says "call Jana Wolff on +49…", so the clerk **blocks it at the border** and says
where ("person name in `next[0]`"), without repeating the value. The rewrite crosses, signed by the Berlin lead.

**Demo beat (40 s).** 38/40, the block, the rewrite, the pseudonymised text arriving in Bengaluru.

## Act 4: Night falls (authority)

*New idea: authority can be delegated, bounded, before you sleep.*

Bengaluru closes first, at 18:00 IST (13:30 in Berlin). The clerk posts **"Bengaluru is closing"**, and the
Bengaluru lead leaves `standing-order handoff TKT-0001 until 09:00`, so the next fix can go to Berlin without
waking anyone. Berlin returns the 38/40 findings late in its afternoon, so the Bengaluru agent works the
second fix through the Indian night.

Berlin 18:05. The clerk posts **"Berlin is closing"**: TKT-0001 may need a release signature tonight. Before
logging off, the Berlin lead types:

```
clerk standing-order release TKT-0001 until 09:00
```

The clerk restates exactly what it may do: sign that release **only if its own independent reconciliation of
that exact commit passes**, once, until 09:00 Berlin time; anything else waits. Both leads are now offline.

For contrast, show what happens **without** a standing order: the request waits ("Berlin is off duty; opens at
09:00, in 13h 00m"), and the agent is told to carry on with other work rather than wait idle.

**Demo beat (40 s).** The closing note, the standing order, the clerk's restatement.

## Act 5: While everyone sleeps (agents don't)

*New idea: the work finishes overnight, and the signatures are still real.*

The Bengaluru agent fixes the importer and hands it to Berlin, signed under the Bengaluru lead's standing
order. The Berlin agent reconciles: **40/40**. It requests the release. **The clerk re-runs the
reconciliation itself** on a fresh copy of that exact commit. It passes, so the Berlin lead's standing order
applies: the clerk signs on their behalf and fast-forwards `main` to exactly that commit, at 03:10 Berlin time.

If the commit had failed (try it with the 38/40 commit), the standing order would not have applied. The release
would have been refused and waited for a person.

**Demo beat (40 s).** Release at 03:10, "signed by berlin-lead (standing order SO-2)".

## Act 6: Morning, and proof

*New idea: afterwards you can prove what happened, not just claim it.*

Berlin 09:01: **"Good morning, Berlin. While you were away: H-4 was signed under your standing order SO-2;
TKT-0001 was released."** The **custody card** in intake lists every crossing, who signed (in person or by
standing order), text digests, refusals along the way, and "personal data that left the EU: none".
`clerk verify-ledger` says intact. Edit one line of the ledger file and run it again: broken, at
that entry.

**Demo beat (30 s).** Morning briefing, custody card, tamper check.
**Total:** about 4 minutes. The ticket closed overnight, without anyone being woken up and without anyone's
authority being skipped.

---

## The one-line pitch per audience

- **Engineers:** rooms are jurisdictions, roles are custody, a deterministic agent is the border, and standing
  orders let authority follow the sun.
- **Managers:** work moves while you sleep, and you wake up to a briefing, not a backlog.
- **Compliance:** every crossing is inspected, signed by a named person (or their bounded delegation), and
  hash-chained.
- **SandboxAQ:** "your context stays on your servers", shown working across two time zones, two vendors and
  one template.

## Where else this applies (same code, different config)

- **Consultancies:** client A's team and documents never reach client B's agents.
- **Healthcare:** patient records stay in the hospital's room; research teams receive de-identified work.
- **Banking in India:** payment data stays in India (RBI localisation) while global teams work from
  pseudonymised cases.
- **On-call releases:** only the on-call lead may approve a deploy, and they can delegate "if the canary is
  green" before sleeping.
