# Narration: lines to record

About 3 minutes. Read it calmly; a pause at each blank line. **Bold** means slow down and lean on it.
Record each section as its own file (`01.m4a`, `02.m4a`, …) so a slip only costs one section.

---

**01: Hook**

In 2023, Meta was fined one point two billion euros for moving Europeans' data to the United States.

Every global company now works with that border. And AI agents are about to cross it thousands of times a day.

**02: Problem**

Say your engineers are in Bengaluru, and your customers' data lives in Berlin. Your agents can work all night.

But they hit two walls. The data isn't allowed to leave the EU. And the person allowed to say "yes, ship it" is asleep.

So teams pick one of two bad options: give the agent everything, or make it wait until morning.

**03: The idea**

We built Customs, on Switch. Each region's agents live in their own room. **Work crosses between rooms. Data doesn't.**

At the border sits a clerk, written in code, not a prompt. It decides what crosses, who has to sign, and what ships.

**04: A ticket arrives**

Here's one real ticket. A German brewery says our invoice totals are off by a cent, and their auditor wants it fixed.

The clerk hands Bengaluru a case file with names, phone numbers, emails and invoice numbers already masked.

**05: The wall**

Can the Bengaluru agent just look at the real invoices? It tries, and Switch refuses: it isn't a member of the Berlin room.

No prompt said no. **The server did.**

**06: The crossing**

It fixes the rounding, pushes the code, and hands the ticket over. The Bengaluru lead signs the exact text that will cross.

Now the ticket is Berlin's, and only inside Berlin do the invoice numbers turn back into real ones.

**07: Real data**

Berlin checks the fix against the customer's real records. **Thirty-eight out of forty.**

The customer's system writes big amounts German style, with a dot and a comma, and our importer was silently dropping those rows. Bengaluru could never have seen that.

Berlin sends back the pattern, never the values, and the clerk masks the invoice numbers on the way out.

**08: Night falls**

Six in the evening in Berlin. Before logging off, the Berlin lead leaves a standing order: release this ticket only if the clerk's own check passes. Once. Until nine.

**09: 3 AM**

Three in the morning. **Nobody awake.** Bengaluru's agent fixes the importer. Berlin's agent reconciles: forty out of forty.

The clerk doesn't take its word for it. It re-runs the check on that exact commit, signs under the standing order, and merges exactly that commit.

**10: Morning**

At nine, the Berlin lead wakes up to this. Fixed, verified and released, **six hours before anyone was awake to approve it.**

Every crossing, who signed it, and how. Personal data that left the EU: none. And the log is tamper-evident: change one line, and it says exactly where.

**11: Close**

Without Switch, these agents couldn't reach each other, couldn't be kept apart, and nobody would know who owns the ticket. With Switch, the whole desk is one template.

Swap the rules, and it's a law firm keeping client files apart, a hospital keeping patient records in-house, or a bank keeping Indian payment data in India.

**Customs. Work crosses borders. Data doesn't.**

---

## Recording tips
- Quiet room, phone or laptop mic about a hand's width away, the same distance for every section.
- Leave a second of silence at the start and end of each file.
- If you stumble, pause and repeat the whole sentence. I'll cut the bad one.
- Say the words as written: the kit aligns your audio to this text to time the screen actions.
- Put the files in `customs/docs/narration/` and tell me. I'll sync the footage to your voice.
