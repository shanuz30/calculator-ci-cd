---
description: Research and report Werkstudent (working-student) job openings in Germany matched against a candidate's CV/profile. Use when the user asks to find student jobs, Werkstudent positions, or internships in a German city, or wants a JD-match scored job-search report.
---

# Werkstudent job-search report workflow

Produces the same structure as `docs/job-search/2026-06-werkstudent-regensburg.md` in the
calculator-ci-cd repo — use that file as a concrete example of the target output.

## 1. Pin down filter criteria before searching
Ask or confirm if unclear:
- **City** + acceptable commute radius
- **Publication window** (e.g. "this month")
- **Minimum JD-match threshold** (the example report used ≥ 60%)
- **Target roles/domains** (e.g. IoT, energy management, software, electrical engineering)

## 2. Extract a candidate profile table
Pull from the CV: degree/program + expected graduation, prior Werkstudent/internship
experience, technical skills (grouped: data/IoT, ML, programming, tools), languages.

## 3. Search and score
1. Use WebSearch / job-aggregator access (Indeed, etc.) — direct fetch of some listing
   sites may 403 inside this environment's network policy; aggregator search usually
   still works.
2. For each candidate listing within the window and city, build a JD-requirement vs.
   CV-coverage table with a ✅ full / ⚠️ partial / ❌ missing rating per requirement, and
   an overall percentage match.
3. Sort into three tiers: **Recommended** (≥ threshold, in-window), **Rejected**
   (checked but below threshold or wrong domain — say why), **Unverified leads**
   (plausible but publication date or full JD text couldn't be confirmed — flag clearly
   as not counted toward the window).

## 4. Installed escalation tools
- **markgrab** — use when a job board 403s on direct WebFetch (e.g. TechBase,
  Mittelbayerische) before marking it as an inaccessible source; it handles
  JS-rendering and anti-bot bypasses that plain WebFetch can't.
- **openregistry** — verify a listing's employer is a real registered company via the
  Handelsregister before recommending the user apply, especially for unfamiliar or
  unverified-lead listings.

## 5. Be honest about source coverage
Always include a short "what was and wasn't accessible" section: which sites blocked
direct fetch (and whether that's the sandbox's network policy or the site itself
blocking crawlers — these are different problems, diagnose before reporting), which
aggregators gave full access, and what therefore might still be missing.

## 5. Close with concrete next steps
Application deadlines (with dates), documents to prepare, and any optional follow-ups
(e.g. a borderline listing just outside the date window worth a manual look).
