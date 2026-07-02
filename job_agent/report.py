"""Deutscher Markdown-Report im Stil von docs/job-search/2026-06-werkstudent-regensburg.md."""

from .api import JOBDETAIL_WEB_URL
from .scoring import COVERAGE_SYMBOL

MODE_LABELS = {
    "werkstudent": "🎓 Werkstudent",
    "vollzeit": "💼 Vollzeit (Pipeline / nach Studienabschluss)",
}


def _de_date(iso_date):
    if not iso_date:
        return "unbekannt"
    parts = str(iso_date)[:10].split("-")
    if len(parts) == 3:
        return f"{parts[2]}.{parts[1]}.{parts[0]}"
    return str(iso_date)


def _job_heading(idx, job):
    new_marker = " 🆕" if job.get("new") else ""
    return (f"### {idx}. {job['employer']} — {job['title']} — "
            f"**Match ≈ {job['percent']} %**{new_marker}")


def _render_recommended(job):
    lines = [
        _job_heading(job["rank"], job),
        "",
        f"- **Standort:** {job['ort']}",
        f"- **Veröffentlicht:** {_de_date(job['published'])}"
        + (f" · **Eintritt:** {_de_date(job['eintritt'])}" if job.get("eintritt") else ""),
        f"- **Link:** {JOBDETAIL_WEB_URL.format(refnr=job['refnr'])}",
    ]
    if job.get("externe_url"):
        lines.append(f"- **Externe Bewerbungsseite:** {job['externe_url']}")
    lines += [
        "",
        "| JD-Anforderung (in der Anzeige erkannt) | CV-Abdeckung | Wertung |",
        "|---|---|---|",
    ]
    for check in job["active"]:
        lines.append(
            f"| {check['label']} | {check['evidence']} | {COVERAGE_SYMBOL[check['coverage']]} |"
        )
    return "\n".join(lines)


def _render_rejected(rejected, max_rows=30):
    if not rejected:
        return "_keine_"
    lines = [
        "| Stelle | Firma / Ort | Veröffentlicht | Grund |",
        "|---|---|---|---|",
    ]
    for job in rejected[:max_rows]:
        lines.append(
            f"| {job['title']} | {job['employer']}, {job['ort']} | "
            f"{_de_date(job['published'])} | {job['reason']} |"
        )
    if len(rejected) > max_rows:
        lines.append(f"\n_… und {len(rejected) - max_rows} weitere aussortierte Anzeigen._")
    return "\n".join(lines)


def render_report(ctx):
    c = ctx["candidate"]
    out = [
        f"# Job-Agent-Report: {ctx['wo']} — {_de_date(ctx['generated'])}",
        "",
        f"**Quelle:** Offizielle Jobsuche-API der Bundesagentur für Arbeit "
        f"(rest.arbeitsagentur.de, [bundesAPI/jobsuche-api](https://github.com/bundesAPI/jobsuche-api))",
        f"**Filterkriterien:** Standort {ctx['wo']} (+ {ctx['umkreis']} km), "
        f"veröffentlicht in den letzten **{ctx['days']} Tagen**, JD-Match **≥ {ctx['min_match']} %**",
        "",
        "> ⚠️ Match-Prozente sind eine Schlüsselwort-Heuristik (\"≈\"), kein Ersatz "
        "für das Lesen der Anzeige. Werkstudenten-Regel: max. **20 Std./Woche** in "
        "der Vorlesungszeit (volle Wochen in der vorlesungsfreien Zeit möglich).",
        "",
        "---",
        "",
        "## Kandidatenprofil",
        "",
        "| Kategorie | Inhalt |",
        "|---|---|",
        f"| Studium | {c['degree']} |",
        f"| Erfahrung | {c['experience']} |",
        f"| Skills | {c['skills_summary']} |",
        f"| Sprachen | {c['languages']} |",
    ]
    for section in ctx["sections"]:
        label = MODE_LABELS.get(section["mode"], section["mode"])
        stats = section["stats"]
        out += [
            "",
            "---",
            "",
            f"## {label} — Empfohlene Treffer (Match ≥ {ctx['min_match']} %)",
            "",
            f"_Suchanfragen: {', '.join(stats['queries'])} · {stats['found']} Anzeigen gefunden, "
            f"{stats['detailed']} Volltexte geprüft._",
            "",
        ]
        if section["recommended"]:
            out.append("\n\n---\n\n".join(_render_recommended(j) for j in section["recommended"]))
        else:
            out.append("_Keine Treffer über der Schwelle in diesem Lauf._")
        out += [
            "",
            f"## {label} — Geprüft und verworfen",
            "",
            _render_rejected(section["rejected"]),
        ]
    out += [
        "",
        "---",
        "",
        "## Quellen-Abdeckung — ehrliche Bilanz",
        "",
        "- ✅ **BA-Jobbörse (offizielle API):** vollständig abgefragt — größte einzelne "
        "Stellenbörse Deutschlands, inkl. vieler Arbeitgeber-Direkteinstellungen.",
        "- ⚠️ **Nicht abgedeckt:** Stellen, die Arbeitgeber *nur* auf eigenen Karriereseiten "
        "oder anderen Portalen (LinkedIn, Indeed, StepStone, TechBase-Board) ausschreiben — "
        "z. B. listen Infineon/Krones Werkstudentenstellen teils nicht in der BA-Jobbörse. "
        "Diese Kanäle weiterhin manuell bzw. per Skill-Workflow prüfen.",
        "- ℹ️ Anzeigen ohne gepflegtes Veröffentlichungsdatum können durch das Zeitfenster fallen.",
        "",
        "## Nächste Schritte",
        "",
        "1. Empfohlene Treffer öffnen (Links oben) und Anzeigentext vollständig lesen — "
        "Match-Prozente sind nur die Vorauswahl.",
        "2. Unterlagen bereithalten: Lebenslauf, aktuelle Immatrikulationsbescheinigung, "
        "Notenübersicht (< 6 Monate), Arbeits-/Werkstudentenzeugnisse.",
        "3. Bei Werkstudentenstellen früh bewerben — viele werden nach wenigen Wochen geschlossen.",
        "4. 🆕-Markierungen zeigen seit dem letzten Lauf neu erschienene Anzeigen.",
        "",
    ]
    return "\n".join(out)
