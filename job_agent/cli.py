"""CLI-Orchestrierung: suchen → vorfiltern → Volltexte bewerten → Report schreiben."""

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from .api import JobsucheClient
from .report import render_report
from .scoring import (is_ausbildung_or_praktikum, is_senior_role, is_werkstudent,
                      load_profile, score_job, title_prescreen)
from .state import SeenJobs


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _offer_meta(offer):
    ort = offer.get("arbeitsort") or {}
    return {
        "refnr": offer.get("refnr", ""),
        "title": offer.get("titel") or offer.get("beruf") or "(ohne Titel)",
        "beruf": offer.get("beruf") or "",
        "employer": offer.get("arbeitgeber") or "unbekannt",
        "ort": " ".join(filter(None, [ort.get("plz"), ort.get("ort")])) or "unbekannt",
        "published": offer.get("aktuelleVeroeffentlichungsdatum") or "",
        "eintritt": offer.get("eintrittsdatum") or "",
    }


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="job_agent",
        description="Job-Agent für die Jobsuche-API der Bundesagentur für Arbeit "
                    "(Werkstudent + Vollzeit, JD-Match gegen Kandidatenprofil).",
    )
    parser.add_argument("--wo", default="Regensburg", help="Ort der Suche (Standard: Regensburg)")
    parser.add_argument("--umkreis", type=int, default=50, help="Umkreis in km (Standard: 50)")
    parser.add_argument("--mode", choices=["werkstudent", "vollzeit", "both"], default="both")
    parser.add_argument("--days", type=int, default=30,
                        help="Nur Anzeigen der letzten N Tage (Standard: 30)")
    parser.add_argument("--min-match", type=int, default=60,
                        help="Empfehlungs-Schwelle in %% (Standard: 60)")
    parser.add_argument("--max-details", type=int, default=40,
                        help="Max. Volltext-Abrufe pro Modus (Standard: 40)")
    parser.add_argument("--max-results", type=int, default=200,
                        help="Max. Suchtreffer pro Suchanfrage (Standard: 200)")
    parser.add_argument("--keywords", nargs="*",
                        help="Zusätzliche Suchbegriffe (ergänzen die Profil-Suchen beider Modi)")
    parser.add_argument("--only-new", action="store_true",
                        help="Nur seit dem letzten Lauf neue Stellen empfehlen")
    parser.add_argument("--out", help="Pfad der Report-Datei "
                        "(Standard: docs/job-search/ba-job-agent-<ort>.md)")
    parser.add_argument("--state-file", default="docs/job-search/.seen_jobs.json")
    parser.add_argument("--profile", help="Pfad zum Kandidatenprofil (JSON)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="Pause zwischen API-Anfragen in Sekunden (Standard: 1.0)")
    return parser


def collect_mode(client, profile, mode, args, state):
    queries = list(profile["searches"][mode])
    if args.keywords:
        queries += args.keywords
    offers = {}
    for query in queries:
        kwargs = {
            "was": query,
            "wo": args.wo,
            "umkreis": args.umkreis,
            "veroeffentlichtseit": args.days,
            "max_results": args.max_results,
        }
        if mode == "vollzeit":
            kwargs["arbeitszeit"] = "vz"
        for offer in client.search(**kwargs):
            refnr = offer.get("refnr")
            if refnr:
                offers.setdefault(refnr, offer)

    cutoff = (date.today() - timedelta(days=args.days)).isoformat()
    rejected, candidates = [], []
    for offer in offers.values():
        meta = _offer_meta(offer)
        title_text = f"{meta['title']} {meta['beruf']}"

        def reject(reason):
            rejected.append({**meta, "reason": reason})

        if is_ausbildung_or_praktikum(meta["title"]):
            reject("Ausbildung/Praktikum/Duales Studium — nicht gesucht")
        elif mode == "werkstudent" and not is_werkstudent(title_text):
            reject("nicht als Werkstudentenstelle ausgeschrieben (nur Erwähnung im Text)")
        elif mode == "vollzeit" and is_werkstudent(title_text):
            reject("Werkstudentenstelle — wird im Werkstudenten-Teil bewertet")
        elif mode == "vollzeit" and is_senior_role(meta["title"]):
            reject("Senior-/Führungsrolle — passt nicht zum Berufseinstieg nach dem Studium")
        # Die API filtert veroeffentlichtseit nicht zuverlässig (geänderte alte
        # Anzeigen rutschen durch), deshalb zusätzlich clientseitig prüfen:
        elif meta["published"] and meta["published"] < cutoff:
            reject(f"außerhalb des {args.days}-Tage-Fensters")
        else:
            ok, reason = title_prescreen(meta["title"], meta["beruf"], profile)
            if ok:
                candidates.append((meta, offer))
            else:
                reject(reason)

    candidates.sort(key=lambda pair: pair[0]["published"], reverse=True)
    to_detail = candidates[:args.max_details]
    for meta, _ in candidates[args.max_details:]:
        rejected.append({**meta, "reason": "nicht im Detail geprüft (Limit --max-details)"})

    recommended = []
    for meta, offer in to_detail:
        try:
            details = client.job_details(meta["refnr"])
        except Exception as exc:  # Auth-Fehler sollen den Lauf abbrechen
            from .api import JobsucheAuthError
            if isinstance(exc, JobsucheAuthError):
                raise
            rejected.append({**meta, "reason": f"Details nicht abrufbar ({exc})"})
            continue
        jd_text = " ".join(filter(None, [
            meta["title"], meta["beruf"],
            details.get("stellenangebotsTitel", ""),
            details.get("stellenangebotsBeschreibung", ""),
        ]))
        result = score_job(jd_text, profile)
        was_new = state.is_new(meta["refnr"])
        state.mark_seen(meta["refnr"], meta["title"], meta["employer"])
        if not result["in_domain"]:
            reason = "zu wenig fachliches Signal im Anzeigentext — Match nicht belastbar"
            if result["percent"] is not None:
                reason += f" (wäre ≈ {result['percent']} %)"
            rejected.append({**meta, "reason": reason})
        elif result["percent"] < args.min_match:
            rejected.append({**meta, "reason": f"Match ≈ {result['percent']} % < Schwelle"})
        elif args.only_new and not was_new:
            rejected.append({**meta, "reason":
                             f"Match ≈ {result['percent']} %, aber bereits in früherem Lauf gemeldet (--only-new)"})
        else:
            recommended.append({
                **meta,
                "percent": result["percent"],
                "active": result["active"],
                "new": was_new,
                "externe_url": details.get("externeUrl") or "",
            })

    recommended.sort(key=lambda j: j["percent"], reverse=True)
    for rank, job in enumerate(recommended, start=1):
        job["rank"] = rank
    return {
        "mode": mode,
        "recommended": recommended,
        "rejected": rejected,
        "stats": {
            "queries": queries,
            "found": len(offers),
            "detailed": len(to_detail),
        },
    }


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    profile = load_profile(args.profile)
    client = JobsucheClient(delay_seconds=args.delay)
    state = SeenJobs.load(args.state_file)

    modes = ["werkstudent", "vollzeit"] if args.mode == "both" else [args.mode]
    sections = [collect_mode(client, profile, mode, args, state) for mode in modes]

    ctx = {
        "wo": args.wo,
        "umkreis": args.umkreis,
        "days": args.days,
        "min_match": args.min_match,
        "generated": date.today().isoformat(),
        "candidate": profile["candidate"],
        "sections": sections,
    }
    out_path = Path(args.out) if args.out else Path(f"docs/job-search/ba-job-agent-{_slug(args.wo)}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_report(ctx), encoding="utf-8")
    state.save()

    for section in sections:
        new_count = sum(1 for j in section["recommended"] if j["new"])
        print(f"[{section['mode']}] {section['stats']['found']} gefunden, "
              f"{section['stats']['detailed']} im Detail geprüft, "
              f"{len(section['recommended'])} empfohlen ({new_count} neu).")
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
