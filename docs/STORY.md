# The Customs story: from the general idea to the full demo

This is the narrative spine for the README, the demo video and the blog. It starts with the general problem,
then adds one idea at a time. Each act introduces exactly one new concept, and each act's demo beat stands on
its own.

---

## Act 0: The general problem (no product yet)

AI agents have become teammates: they write code, answer customers, reconcile accounts. But every real
organisation has **borders**, and agents ignore them or stop at them:

| Border | Example |
|---|---|
| **Data** | EU customer data must stay in the EU (GDPR). Indian payment data must stay in India (RBI). Client A's documents must never reach the team working for client B. |
| **Authority** | Only the Berlin lead may approve what touches EU customers. Only the on-call engineer may approve a deploy. |
| **Time** | The person allowed to say "yes" is asleep for the next eight hours. |

A single "do everything" agent can't respect these borders, because it would need every permission at once.
Teams end up choosing between giving the agent too much access and doing the work by hand.

**The question:** how do you let AI work flow across an organisation while every border still holds?

## Act 0.5: The general solution (one sentence, one picture)

> **Put each team's agents inside its own jurisdiction, and let work, not data, cross between jurisdictions
> through a border that is enforced in code.**

```
   [ Jurisdiction A ]              [ Border ]               [ Jurisdiction B ]
   people + agents   --work-->  custody · check · sign  --work-->  people + agents
   (their data stays)            ledger every crossing             (their data stays)
```

On Switch, this maps one-to-one onto primitives that already exist:

| Concept | Switch primitive |
|---|---|
| Jurisdiction | A **room**. Membership is enforced by the server. |
| "Who owns this task right now" | An **exclusive role** in that room: one holder at a time. |
| The border | A **custom agent** (the Customs clerk), the only member of every room. Deterministic, not an AI. |
| Crossing | A structured handoff message, a person's signature, and a ledger entry. |
| The whole setup | One **template**. |

Customs is general: jurisdictions, routes, approvers and what counts as protected data are all configuration.
The rest of this story is **one example**, an EU customer's bug fixed by a team in Bengaluru and a team in Berlin.

---

## Act 1: The simplest crossing. A task changes hands, a person signs.

*New concept: custody and a signed handoff.*

- A ticket is opened in the intake room. The clerk puts it in **Bengaluru's custody** and tells the agent that
  holds the `investigator` role.
- The Bengaluru agent fixes something and posts a handoff (summary, what's done, what's next, evidence, commit).
- The clerk asks the **Bengaluru lead** to sign *this exact text*. They type `approve H-1`.
- Custody moves to **Berlin**. The intake room shows the clocks: Bengaluru 15:10 (open), Berlin 10:40 (open).

**Demo beat (30 s):** handoff, signature, custody moves. Nothing else yet.
**What it shows:** work moved, someone accountable signed, and everyone can see who owns it now.

## Act 2: The wall. Why the work has to move at all.

*New concept: a jurisdiction holds data the other side may not see.*

- Someone asks the Bengaluru agent: "Can you just check the customer's real invoices?"
- It tries to read the Berlin room, and **Switch refuses**: it isn't a member. It says so in the room.
- No prompt said "don't". The server did.

**Demo beat (20 s):** the refusal, verbatim.
**What it shows:** the border isn't a policy document. Room membership is enforced by the server.

## Act 3: The border check. Only safe text crosses.

*New concept: what crosses is inspected; personal data is blocked; identifiers are pseudonymised.*

- Bengaluru only ever saw a **case file** with `[INV-1]` instead of invoice numbers, and no names or emails.
- Inside Berlin, the clerk turns `[INV-1]` back into the real invoice number for the Berlin agent.
- On the way back, a draft says "call Jana Wolff on +49…". The clerk **blocks it at the border** and says
  where ("person name in `next[0]`"), without repeating the value. The agent rewrites it as a pattern.

**Demo beat (40 s):** the block, the rewrite, the pseudonymised text arriving in Bengaluru.
**What it shows:** the border reads every crossing, and it fails closed.

## Act 4: Real data finds what the sample couldn't. The round trip.

*New concept: the jurisdictions need each other.*

- Berlin reconciles Bengaluru's fix against the customer's real records: **38/40**. Two invoices still fail.
  The customer's ERP writes `1.234,50`, and Ledgerly silently drops those rows.
- Bengaluru could never have found it from a sample, and Berlin needs Bengaluru's code context to fix it. So
  the ticket goes back (signed by the Berlin lead), gets fixed, and returns: **40/40**.

**Demo beat (40 s):** 38/40, then back, then 40/40.
**What it shows:** this isn't bureaucracy. Neither side could have finished alone.

## Act 5: A release you can trust.

*New concept: verify, sign, merge exactly that, and prove it afterwards.*

- Berlin asks to release. **The clerk re-runs the reconciliation itself** on a fresh copy of that exact
  commit. It doesn't take the agent's word.
- The Berlin lead signs. The clerk fast-forwards `main` to exactly that commit.
- The **custody card** posts to intake: every crossing, who signed, text digests, refusals along the way, and
  "personal data that left the EU: none".
- `@customs-clerk verify-ledger`: intact. Edit one line in the ledger file and run it again: broken, at that entry.

**Demo beat (40 s):** the independent check, the signature, the custody card, the tamper check.
**What it shows:** afterwards you can prove what happened, not just claim it.

---

## The one-line pitch per audience

- **Engineers:** rooms are jurisdictions, roles are custody, and a deterministic agent is the border.
- **Compliance:** every crossing is inspected, signed by a named person, and hash-chained.
- **SandboxAQ:** "your context stays on your servers", shown working across two teams, two vendors and one
  template.

## Where else this applies (same code, different config)

- **Consultancies:** client A's team and documents never reach client B's agents.
- **Healthcare:** patient records stay in the hospital's room, and research teams receive de-identified work.
- **Banking in India:** payment data stays in India under RBI localisation, while global teams work from
  pseudonymised cases.
- **Regulated releases:** only a licensed person in the target market may sign what ships there.
