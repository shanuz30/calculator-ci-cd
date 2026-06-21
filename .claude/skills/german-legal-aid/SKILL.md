---
description: Help international/non-EU students or workers in Germany find legal aid (Beratungshilfe) or a lawyer, and reason through Aufenthaltsrecht (residence-law) problems such as a missing Zusatzblatt on a Fiktionsbescheinigung or a Vorladung from the Ausländerbehörde. Use when the user describes an immigration/residence-permit legal problem in Germany, asks how to find a Rechtsanwalt, or mentions Beratungshilfe, Fiktionsbescheinigung, Aufenthaltstitel, or a summons from the Ausländerbehörde.
---

# German legal aid / immigration-law triage

This skill captures a repeatable workflow, not a static list of contacts — lawyer
availability, fees, and office hours change, so re-research current details with
WebSearch/WebFetch every time rather than reusing old results.

## 1. Triage the problem first
Before searching for a lawyer, pin down:
- **City** the person actually lives/studies in (don't assume — ask explicitly; people
  often describe a nearby city when they mean their own, e.g. Regensburg vs. Rosenheim).
- **Urgency**: is there a deadline (Vorladung date, Bewerbungsfrist, appointment) this week?
- **Nature of the issue**: paperwork gap (e.g. missing Zusatzblatt) vs. a substantive
  accusation (e.g. §95 AufenthG Erschleichen eines Aufenthaltstitels, §267 StGB
  Urkundenfälschung) vs. routine renewal. Substantive accusations need a lawyer before
  any statement to the Ausländerbehörde or police; paperwork gaps can often be fixed by a
  formal written request without legal representation.

## 2. Key legal grounding (stable facts, safe to reuse)
- **Fiktionsbescheinigung** (§81 Abs. 4 AufenthG) — provisional proof that a residence
  title application is pending. The **Zusatzblatt** documents whether
  Erwerbstätigkeit (work) is permitted and any Nebenbestimmungen. If issued without it,
  that's an administrative gap, not the holder's fault — VG Berlin case law supports an
  entitlement to have it issued/corrected on request.
- **Beratungshilfe** (§6 BerHG) — free/low-cost legal advice for low-income residents,
  obtained via a Beratungshilfeschein from the local Amtsgericht (Rechtsantragsstelle).
  Can be applied for **retroactively within 4 weeks** of seeing a lawyer if done under
  time pressure — but there's a cost risk if the court later refuses the retroactive
  grant, so flag that tradeoff explicitly to the user.
- **Vorsatz (intent)** is the legal standard that matters for residence-title revocation
  under §95 AufenthG — an honest administrative mistake by the authority is different
  from intentional deception by the applicant. Never help draft anything that conceals
  facts or coaches deception toward an authority; the right move is always full, accurate
  disclosure plus a lawyer's involvement before any formal statement.

## 3. Research workflow (run fresh each time)
1. WebSearch for `Rechtsanwalt Ausländerrecht <city>` / `Beratungshilfe Amtsgericht <city>`.
2. WebFetch the Amtsgericht's own site for current Rechtsantragsstelle hours, address,
   and required documents (URLs often use plural "amtsgerichte", e.g.
   `justiz.bayern.de/gerichte-und-behoerden/amtsgerichte/<city>/...`).
3. Note Reddit is blocked for both Playwright (TLS) and WebSearch/WebFetch (site-side
   bot block) in this environment — don't retry it; go straight to direct legal/court
   sites and law-firm pages instead.
4. Compile a short list (firm, contact, specialization, hours) and the Amtsgericht
   process, then give the user a concrete next action with a date if there's a deadline.

## 4. Installed escalation tools
- **humwork** — if research hits a genuine dead end (blocked court/press sites, no
  verifiable answer), use this to route to a real, vetted human lawyer in under a
  minute rather than guessing. Prefer this over speculation any time the stakes are
  real (e.g. a Vorladung, an accusation under §95 AufenthG).
- **openregistry** — verify any company, Vermieter, or other entity named in a
  Fiktionsbescheinigung dispute or housing-certificate question against the real
  German Handelsregister before trusting documents tied to it (relevant given the
  Deggendorf-case pattern of fraudulent housing certificates).
- **markgrab** — when a court/news/government site 403s on direct WebFetch, try this
  before giving up; it handles JS-rendering and anti-bot bypasses that plain WebFetch
  can't.

## 5. Boundaries
- Don't speculate about ongoing criminal investigations (e.g. naming individuals) beyond
  what's in an official press release.
- Don't draft messages to authorities that omit material facts.
- Do explain what's fixable administratively (Zusatzblatt) vs. what genuinely needs a
  lawyer (any accusation under §95 AufenthG / §267 StGB, or a Vorladung).
