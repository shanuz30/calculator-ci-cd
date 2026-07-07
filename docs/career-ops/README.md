# career-ops Starter-Konfiguration

Vorbereitete Dateien für [santifer/career-ops](https://github.com/santifer/career-ops)
(MIT, läuft lokal in Claude Code) — abgestimmt auf das Kandidatenprofil aus
`job_agent/candidate_profile.json` und das BSH-Werkstudentenzeugnis.

## Nutzung (auf dem eigenen Rechner)

```bash
npx @santifer/career-ops init
cd career-ops
# Dateien aus diesem Ordner übernehmen:
cp <repo>/docs/career-ops/cv.md ./cv.md
cp <repo>/docs/career-ops/profile.yml ./config/profile.yml
claude   # dann Job-URLs einfügen oder /career-ops scan
```

## Vorher ausfüllen

Beide Dateien enthalten `TODO(...)`-Platzhalter (Telefon, LinkedIn, sdp/SappZ-Daten,
Bachelor, Gehaltsuntergrenze, Aufenthaltsstatus). **Telefonnummer und private Details
nur lokal eintragen, nicht in dieses Repo committen.**

## Zusammenspiel mit dem BA-Job-Agenten

1. `python job_agent.py` (bzw. der wöchentliche Actions-Lauf) findet Stellen der
   Bundesagentur für Arbeit → `docs/job-search/ba-job-agent-regensburg.md`
2. Vielversprechende Links aus dem Report in career-ops einfügen
3. career-ops bewertet (A–F), erstellt das zugeschnittene ATS-CV-PDF und trackt
   die Bewerbung
