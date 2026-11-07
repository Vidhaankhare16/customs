# Submission: Flip the Switch (WeMakeDevs × DevTools Academy × Switch)

Every answer is in its own copy block, written as plain text: no markdown, and one line per paragraph. Copy a block's
contents straight into the matching form field. In VS Code's Markdown preview or on GitHub, the copy button sits at
the block's top right. Items marked **YOU** need your account or a click.

## Checklist

| Item | Status |
|---|---|
| Public repository | Done: <https://github.com/Vidhaankhare16/customs> (public, pushed) |
| Demo video (under 3 min) | Done: **2:54**, 1920×1080, AI narration with burned-in captions, one live take of the real system. File: `C:\Users\VICTUS 15\Desktop\demo-video-kit\videos\customs\out\video.mp4`. **YOU:** upload it to YouTube as *Unlisted* with the title and description below, then paste the link into the form and into `README.md` line 6 |
| README explaining Switch use | `README.md` in the repo (agents, channels, how to run) |
| Blog post (optional, Best Blog) | Draft ready: `docs/BLOG.md`. **YOU:** publish it on dev.to or Hashnode and paste the link |
| #HowISwitch post (optional) | Text below. **YOU:** post it on LinkedIn or X with the video |
| Wispr usage card | Not applicable (not built with Wispr Flow) |
| Pull requests (Track 03) | Not applicable |

### Your remaining steps, in order (about 20 minutes)
1. Upload `video.mp4` to YouTube as **Unlisted** (title, description and chapters are below).
2. Put the YouTube link into `README.md` line 6, replacing `_link to be added_`. Commit and push, or ask Claude to.
3. Publish `docs/BLOG.md` on dev.to or Hashnode, adding the video link near the top.
4. Post the #HowISwitch text below on LinkedIn or X, with the video attached.
5. Fill in the form with Parts 1–3 below, plus the video and blog links. Deadline: **Nov 7, 11:59 PM IST**.

---

## Part 1: Project details

**Project title**
```text
Customs: follow-the-sun AI work where customer data stays in its region
```

**Tracks you are submitting for**
```text
Track 01: Best Business Workflow
```
Also tick the Best Blog side track if the form lists it, once the blog is published.

**Project description** (what problem it solves, and who it's for)
```text
Global teams run AI agents around the clock, but two borders stop the work. Customer data isn't allowed to leave its region (GDPR in the EU, RBI localisation in India), and the person allowed to approve the work is asleep. So teams either give an agent everything, all access plus auto-approve, or keep a human in every loop and let the agent wait all night.

Customs fixes that on Switch. Each region's agents live in their own Switch room. Work crosses between rooms; data doesn't. A deterministic "clerk" agent sits at the border, written in code, not a prompt, and decides what crosses:
- only the holder of a room's exclusive role can hand work on;
- personal data leaving the EU is blocked, and invoice numbers are pseudonymised on the way out;
- every crossing needs a named person's signature on the exact text;
- before release, the clerk re-verifies the exact commit itself;
- everything goes into a tamper-evident, hash-chained ledger.

Approvers can also leave bounded "standing orders" before going off duty ("release this ticket only if your own check passes, once, until 09:00"). Work then finishes overnight without anyone's authority being skipped.

In the demo, a real Claude Code agent in Bengaluru fixes an EU customer's invoice bug from a masked case file. A second agent in Berlin checks the fix against the real records, finds a second bug only real data could reveal (38 of 40), and sends back the pattern, never the values. The fix is released at 03:00 Berlin time, six hours before anyone woke up, with both signatures intact. It's for any company whose agents work across regions, clients or legal boundaries: SaaS support, consultancies, hospitals, banks.
```

**GitHub repository**
```text
https://github.com/Vidhaankhare16/customs
```

**Demo video:** your YouTube unlisted link (**YOU**, after uploading).

**Live demo or deployment:** leave blank. It runs on your own Switch server, and the README has a one-template setup.

### YouTube upload details
**Visibility:** Unlisted

**Title**
```text
Customs: AI agents that work across borders while customer data stays home (Flip the Switch)
```

**Description** (the chapter lines make YouTube show chapters automatically)
```text
Your AI agents don't sleep. Your approvers do, and your customers' data isn't allowed to leave its region. Customs is a border for agent work, built on Switch: work crosses between regional rooms, data doesn't, and every crossing is checked in code, signed by a person, and written to a tamper-evident ledger.

Real run: Claude Code agents in Bengaluru and Berlin, Switch rooms in Mattermost, a deterministic clerk agent.
Code: https://github.com/Vidhaankhare16/customs

0:00 The stakes
0:15 The problem
0:36 The idea
0:51 One real ticket
1:05 The wall
1:16 The crossing
1:31 Real data
1:51 Night falls
2:02 Three in the morning
2:20 Morning
2:36 Why Switch
```

---

## Part 2: Track details (optional)

**Pull requests:** none, leave blank.

**Blog post:** your dev.to or Hashnode link (**YOU**, after publishing `docs/BLOG.md`).

**Wispr usage card:** not applicable, leave blank.

**#HowISwitch post** (LinkedIn or X, attach the video)
```text
AI agents don't sleep. The people allowed to approve their work do, and EU customer data isn't allowed to leave the EU.

For #FlipTheSwitch I built Customs on Switch: each region's agents get their own room, and a deterministic "clerk" agent guards the border between them. Work crosses. Data doesn't. Every crossing is signed by a person (or their bounded standing order), and the release is re-verified in code.

In the demo, a bug in an EU customer's invoices gets fixed in Bengaluru, verified against the real records in Berlin, and released at 3 AM, six hours before anyone woke up. Zero personal data left the EU.

Code: https://github.com/Vidhaankhare16/customs
#HowISwitch @WeMakeDevs @DevToolsAcademy
```
On X this is longer than 280 characters. Post it as a short thread, or keep the first two paragraphs plus the link.

---

## Part 3: How you used Switch

**How did you use Switch in your project?** (agents, platforms, real work, how teammates work with it)
```text
Agents:
- Two Claude Code agents, each a managed agent on my machine: in-investigator, the Bengaluru engineer, and eu-verifier, the Berlin verifier next to the customer vault.
- One custom agent I wrote against the Switch agent protocol: the Customs clerk, about 400 lines of standard-library Python and deliberately not an LLM.

Platform: Mattermost, the server Switch bundles. The template also works with Slack, Teams, Discord or Telegram.

Setup: a Switch room group with three linked rooms. customs-intake is where people and the clerk open tickets. customs-in holds the Bengaluru agent and its lead. customs-eu holds the Berlin agent, its lead and the only access to EU data. Each regional agent is a member of one room only, so Switch's own membership check stops the Bengaluru agent reading Berlin's room. Each room has an exclusive role (investigator, verifier) that marks who holds custody, and the clerk reads the live role holders from get_room_detail. One template creates the whole desk.

Real work:
- The agents reproduce, fix, test, commit and push real code.
- The Berlin agent reconciles fixes against the customer's real records.
- The clerk validates every handoff, masks and blocks personal data, collects human signatures, re-runs verification at the exact commit, and fast-forwards main.

How teammates work with it, in plain chat:
- Support opens a ticket with "clerk open C-DE-0042 ...".
- Leads sign with "approve H-3".
- Before going off duty, a lead types "clerk standing-order release TKT-0001 until 09:00".
- Everyone sees the custody trail, closing notes and "while you were away" morning briefings in the rooms.
```

**What did you like about Switch, and what would you improve?**
```text
What I liked:
- Room membership is enforced by the server. Data residency became a real boundary, not a prompt.
- Exclusive roles with leases were a perfect fit for custody.
- Templates made the whole desk reproducible, and agents from different vendors can share one room.
- The agent protocol is simple enough to write a non-AI agent with plain HTTP, and the docs MCP server helped a lot.

What got in the way (on Windows, Console v0.40.1):
- The template form couldn't create managed agents on my machine. Every provider showed "Not supported here", while the New agent form worked. I fell back to creating agents by hand plus a rooms-only template.
- A slow template run finished on the server after the Console timed out. Retrying created duplicate rooms.
- A custom agent registered with the bootstrap token is owned by a system account. I couldn't change who may address it, so mentions got an automatic "not permitted" reply.
- The repo's protocol docs and the published docs disagree (SSE vs WebSocket, register-known vs POST /agents).
- Closing the local server's terminal window stops the server, which is easy to do by accident.

What I'd want next:
- A way to set a custom agent's owner and addressing at registration.
- First-class "approval" events, so a signature isn't just a chat message.
- Role-scoped tokens, so a border agent could act with less than an owner's reach.
```
