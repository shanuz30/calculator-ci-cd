# calculator-ci-cd
Using Calculator and pytest
Oxocard Program from source

## Files
- `mqtt_sensor_monitor.py` — Oxocard MQTT sensor script (CO2/NOx/temperature → HiveMQ). Formerly misnamed `updated from the source.npy`.
- `job_agent/` + `job_agent.py` — Job-Agent für die **offizielle Jobsuche-API der Bundesagentur für Arbeit** (kein HTML-Scraping; API dokumentiert unter [bundesAPI/jobsuche-api](https://github.com/bundesAPI/jobsuche-api)).

## Job-Agent (Agentur für Arbeit)

Sucht Werkstudenten- und Vollzeitstellen, bewertet jede Anzeige per JD-Match
gegen das Kandidatenprofil (`job_agent/candidate_profile.json`) und schreibt
einen deutschen Markdown-Report nach `docs/job-search/`.

```bash
pip install -r requirements.txt
python job_agent.py                          # Werkstudent + Vollzeit, Regensburg + 50 km
python job_agent.py --mode werkstudent --wo München --umkreis 25 --days 14
python job_agent.py --only-new               # nur seit letztem Lauf neue Treffer empfehlen
```

- Läuft automatisch **jeden Montag** per GitHub Actions (`.github/workflows/job-agent.yml`)
  und committet den aktualisierten Report; bereits gemeldete Stellen werden in
  `docs/job-search/.seen_jobs.json` gemerkt und mit 🆕 von neuen unterschieden.
- Match-Prozente sind eine Schlüsselwort-Heuristik ("≈") — Anzeige immer selbst lesen.
- Sollte der öffentliche API-Key rotiert werden: `JOBSUCHE_API_KEY` als Umgebungsvariable setzen.
- Abdeckung: nur die BA-Jobbörse; Stellen, die Arbeitgeber ausschließlich auf eigenen
  Karriereseiten/LinkedIn/Indeed ausschreiben, tauchen hier nicht auf.
- Tests: `python -m pytest tests/ -q` (ohne Netzwerkzugriff).

## Security note
MQTT broker credentials were previously committed in this repository and remain
visible in git history. They must be treated as compromised: rotate the password
in the HiveMQ Cloud console. Real credentials are never committed — the script
contains placeholders to be filled in locally on the device.
