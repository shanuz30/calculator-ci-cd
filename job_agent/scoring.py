"""JD-Match-Bewertung: Stellenbeschreibung gegen das Kandidatenprofil.

Heuristik, keine exakte Wissenschaft — Prozentwerte sind bewusst als "≈"
zu lesen. Bewertet werden nur Anforderungs-Checks, deren Schlüsselwörter in
der Anzeige tatsächlich vorkommen ("aktive" Checks); jeder Check trägt mit
seiner Abdeckung (voll=1.0 / teilweise=0.5 / fehlt=0.0) gewichtet bei.
"""

import json
import re
from pathlib import Path

DEFAULT_PROFILE_PATH = Path(__file__).parent / "candidate_profile.json"

COVERAGE_VALUE = {"voll": 1.0, "teilweise": 0.5, "fehlt": 0.0}
COVERAGE_SYMBOL = {"voll": "✅ voll", "teilweise": "⚠️ teilweise", "fehlt": "❌ fehlt"}

WERKSTUDENT_RE = re.compile(r"werkstudent|working\s*student|werkstudierende", re.IGNORECASE)
AUSSCHLUSS_TITEL_RE = re.compile(r"\bausbildung\b|\bpraktikum\b|\bpraktikant|\bduales?\s+studium", re.IGNORECASE)
# Führungs-/Senior-Rollen passen nicht zu Berufseinstieg nach dem Studium
SENIOR_TITEL_RE = re.compile(r"senior|principal|head\s+of|leiter|leitung|führungskraft|geschäftsführ", re.IGNORECASE)

_WORDCHARS = "a-z0-9äöüß"


def load_profile(path=None):
    profile_path = Path(path) if path else DEFAULT_PROFILE_PATH
    with open(profile_path, encoding="utf-8") as fh:
        return json.load(fh)


def keyword_in_text(keyword, text_lower):
    """Schlüsselwort-Suche: kurze Wörter (≤ 3 Zeichen, z. B. KI, AI, REM, SPS)
    nur an Wortgrenzen, längere als Teilstring (deckt deutsche Komposita ab,
    z. B. 'entwickl' → 'Softwareentwicklung')."""
    kw = keyword.lower()
    if len(kw) <= 3:
        return re.search(
            rf"(?<![{_WORDCHARS}]){re.escape(kw)}(?![{_WORDCHARS}])", text_lower
        ) is not None
    return kw in text_lower


def is_werkstudent(text):
    return WERKSTUDENT_RE.search(text or "") is not None


def is_ausbildung_or_praktikum(title):
    return AUSSCHLUSS_TITEL_RE.search(title or "") is not None


def is_senior_role(title):
    return SENIOR_TITEL_RE.search(title or "") is not None


def title_prescreen(title, beruf, profile):
    """Grobe Titel-Vorauswahl vor dem (teuren) Abruf der Stellen-Details.

    Rückgabe (ok, grund): Negativ-Treffer ohne gleichzeitigen Positiv-Treffer
    lehnen ab; sonst ist mindestens ein Positiv-Schlüsselwort nötig.
    """
    text = f"{title or ''} {beruf or ''}".lower()
    screen = profile["title_prescreen"]
    positive_hit = any(keyword_in_text(kw, text) for kw in screen["positive"])
    negative_hits = [kw for kw in screen["negative"] if keyword_in_text(kw, text)]
    if negative_hits and not positive_hit:
        return False, f"Titel außerhalb der Zieldomäne ({negative_hits[0]})"
    if not positive_hit:
        return False, "Titel ohne Bezug zur Zieldomäne"
    return True, ""


def score_job(jd_text, profile):
    """Bewertet einen JD-Volltext. Rückgabe-Dict:

    percent      – gerundeter Match in %, None wenn zu wenig Domänen-Signal
    active       – Liste aktiver Checks (label, coverage, evidence, hits)
    domain_hits  – Anzahl aktiver Checks mit domain=true
    in_domain    – genug fachliches Signal für eine belastbare Bewertung?
    """
    text_lower = (jd_text or "").lower()
    active = []
    for check in profile["requirement_checks"]:
        hits = [kw for kw in check["jd_keywords"] if keyword_in_text(kw, text_lower)]
        if hits:
            active.append({
                "label": check["label"],
                "coverage": check["coverage"],
                "evidence": check["evidence"],
                "weight": check["weight"],
                "domain": check.get("domain", False),
                "hits": hits,
            })
    domain_hits = sum(1 for c in active if c["domain"])
    in_domain = domain_hits >= profile.get("min_domain_checks", 2)
    percent = None
    if active:
        total = sum(c["weight"] for c in active)
        covered = sum(c["weight"] * COVERAGE_VALUE[c["coverage"]] for c in active)
        percent = round(100 * covered / total)
    return {
        "percent": percent,
        "active": active,
        "domain_hits": domain_hits,
        "in_domain": in_domain,
    }
