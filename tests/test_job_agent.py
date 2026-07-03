# -*- coding: utf-8 -*-
"""Tests für den Job-Agenten — komplett ohne Netzwerkzugriff (Fake-Session)."""

import base64

import pytest

from job_agent.api import JobsucheAuthError, JobsucheClient, encode_refnr
from job_agent.cli import build_arg_parser, collect_mode
from job_agent.report import render_report
from job_agent.scoring import (is_ausbildung_or_praktikum, is_senior_role,
                               is_werkstudent, keyword_in_text, load_profile,
                               score_job, title_prescreen)
from job_agent.state import SeenJobs

PROFILE = load_profile()


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.responses.pop(0)


def make_client(responses):
    return JobsucheClient(session=FakeSession(responses),
                          delay_seconds=0, backoff_seconds=0)


# ---------------------------------------------------------------- API-Client

def test_encode_refnr_is_urlsafe_base64():
    refnr = "11849-P2130715-1-S"
    assert encode_refnr(refnr) == base64.urlsafe_b64encode(refnr.encode()).decode()


def test_search_stops_on_short_page_and_dedupes():
    offers = [{"refnr": "A"}, {"refnr": "B"}, {"refnr": "A"}]
    client = make_client([FakeResponse(payload={"stellenangebote": offers})])
    result = client.search(was="Werkstudent", wo="Regensburg", umkreis=50)
    assert [o["refnr"] for o in result] == ["A", "B"]
    assert len(client.session.calls) == 1
    assert client.session.calls[0]["headers"]["X-API-Key"] == "jobboerse-jobsuche"


def test_search_paginates_until_max_results():
    page1 = {"stellenangebote": [{"refnr": f"R{i}"} for i in range(100)]}
    page2 = {"stellenangebote": [{"refnr": "R100"}, {"refnr": "R101"}]}
    client = make_client([FakeResponse(payload=page1), FakeResponse(payload=page2)])
    result = client.search(was="x", max_results=150)
    assert len(result) == 102
    assert len(client.session.calls) == 2


def test_auth_error_names_env_var():
    client = make_client([FakeResponse(status_code=403)])
    with pytest.raises(JobsucheAuthError, match="JOBSUCHE_API_KEY"):
        client.search(was="x")


def test_server_error_is_retried_then_succeeds():
    client = make_client([
        FakeResponse(status_code=500),
        FakeResponse(payload={"stellenangebote": [{"refnr": "A"}]}),
    ])
    assert client.search(was="x")[0]["refnr"] == "A"
    assert len(client.session.calls) == 2


def test_job_details_uses_encoded_refnr_in_url():
    client = make_client([FakeResponse(payload={"stellenangebotsTitel": "t"})])
    client.job_details("11849-P2130715-1-S")
    assert client.session.calls[0]["url"].endswith(encode_refnr("11849-P2130715-1-S"))


# ------------------------------------------------------------------- Scoring

def test_keyword_boundaries_for_short_keywords():
    assert not keyword_in_text("ki", "praktikum in der küche")   # kein Teilwort-Match
    assert keyword_in_text("ki", "ki-entwicklung im team")
    assert keyword_in_text("python", "gute python-kenntnisse")
    assert keyword_in_text("entwickl", "softwareentwicklung")    # deutsches Kompositum


def test_werkstudent_classification():
    assert is_werkstudent("Werkstudent (m/w/d) Softwareentwicklung")
    assert is_werkstudent("Working Student Data Engineering")
    assert not is_werkstudent("Softwareentwickler (m/w/d)")
    assert is_ausbildung_or_praktikum("Ausbildung zum Fachinformatiker")
    assert is_ausbildung_or_praktikum("Praktikum im Bereich IoT")
    assert not is_ausbildung_or_praktikum("Werkstudent IoT")


def test_senior_roles_detected():
    assert is_senior_role("Teamleiter Entwicklung (m/w/d)")
    assert is_senior_role("Senior Hardware Engineer")
    assert is_senior_role("Leiter Industrialisierung - Spritzguss")
    assert not is_senior_role("Junior Software Developer")
    assert not is_senior_role("Prüfingenieur (w/m/d)")


def test_title_prescreen_rejects_off_domain_and_keeps_technical():
    ok, reason = title_prescreen("Werkstudent (m/w/d)", "Servicekraft - Gastronomie", PROFILE)
    assert not ok and "gastronomie" in reason
    ok, _ = title_prescreen("Werkstudent Softwareentwicklung", "Informatiker/in", PROFILE)
    assert ok
    # Negativ- UND Positiv-Treffer (z. B. Vertriebsingenieur) → behalten
    ok, _ = title_prescreen("Vertriebsingenieur (m/w/d)", "", PROFILE)
    assert ok
    ok, reason = title_prescreen("Werkstudent (m/w/d) HR", "Recruiter/in", PROFILE)
    assert not ok


def test_score_job_strong_match():
    jd = ("Wir suchen einen Werkstudenten mit Python-Kenntnissen für unsere "
          "IoT-Plattform (MQTT). Erfahrung mit Docker sowie gute Deutschkenntnisse.")
    result = score_job(jd, PROFILE)
    assert result["in_domain"]
    assert result["percent"] >= 80
    labels = {c["label"]: c["coverage"] for c in result["active"]}
    assert labels["Python"] == "voll"
    assert labels["Deutschkenntnisse"] == "teilweise"


def test_score_job_gap_heavy_match_is_low():
    jd = "SAP-Kenntnisse und SPS-Programmierung (Simatic) zwingend erforderlich."
    result = score_job(jd, PROFILE)
    assert result["percent"] is not None and result["percent"] <= 30


def test_score_job_thin_signal_is_not_in_domain():
    # Nur Studiengang + Sprachen erwähnt → zu wenig fachliches Signal
    jd = ("Abgeschlossenes Studium der Elektrotechnik, gute Deutsch- und "
          "Englischkenntnisse. Wir bieten ein tolles Team.")
    result = score_job(jd, PROFILE)
    assert not result["in_domain"]


def test_score_job_no_signal_is_out_of_domain():
    result = score_job("Wir suchen freundliche Kellner für unser Restaurant.", PROFILE)
    assert result["percent"] is None
    assert not result["in_domain"]


# --------------------------------------------------------------------- State

def test_state_roundtrip_and_dedupe(tmp_path):
    path = tmp_path / "seen.json"
    state = SeenJobs.load(path)
    assert state.is_new("R1")
    state.mark_seen("R1", "Titel", "Firma")
    state.save()
    reloaded = SeenJobs.load(path)
    assert not reloaded.is_new("R1")
    assert reloaded.is_new("R2")
    assert len(reloaded) == 1


# ------------------------------------------------------------ CLI + Pipeline

class FakeClient:
    """Duck-typing-Ersatz für JobsucheClient in der Pipeline."""

    def __init__(self, offers, details):
        self.offers = offers
        self.details = details

    def search(self, **kwargs):
        return self.offers

    def job_details(self, refnr):
        return self.details[refnr]


def _offer(refnr, titel, beruf="", published="2099-01-01"):
    return {
        "refnr": refnr,
        "titel": titel,
        "beruf": beruf,
        "arbeitgeber": "Testfirma GmbH",
        "arbeitsort": {"plz": "93053", "ort": "Regensburg"},
        "aktuelleVeroeffentlichungsdatum": published,
    }


def test_collect_mode_recommends_and_rejects(tmp_path):
    offers = [
        _offer("GOOD", "Werkstudent Softwareentwicklung Python (m/w/d)"),
        _offer("GASTRO", "Werkstudent (m/w/d)", beruf="Servicekraft - Gastronomie"),
        _offer("OLD", "Werkstudent Embedded Software", published="2000-01-01"),
        _offer("FULLTIME", "Softwareentwickler (m/w/d)"),
    ]
    details = {"GOOD": {"stellenangebotsBeschreibung":
                        "Python, MQTT, IoT, Git, Linux, Docker, Grafana, "
                        "Elektrotechnik-Studium, gute Deutschkenntnisse."}}
    args = build_arg_parser().parse_args(
        ["--state-file", str(tmp_path / "seen.json"), "--days", "30"])
    state = SeenJobs.load(args.state_file)
    section = collect_mode(FakeClient(offers, details), PROFILE, "werkstudent", args, state)

    assert [j["refnr"] for j in section["recommended"]] == ["GOOD"]
    assert section["recommended"][0]["new"]
    assert section["recommended"][0]["percent"] >= 60
    reasons = {j["refnr"]: j["reason"] for j in section["rejected"]}
    assert "gastronomie" in reasons["GASTRO"]
    assert "Fenster" in reasons["OLD"]
    assert "Werkstudentenstelle" in reasons["FULLTIME"]


def test_collect_mode_only_new_suppresses_seen(tmp_path):
    offers = [_offer("GOOD", "Werkstudent Python IoT (m/w/d)")]
    details = {"GOOD": {"stellenangebotsBeschreibung":
                        "Python, MQTT, IoT, Elektrotechnik, Deutschkenntnisse."}}
    args = build_arg_parser().parse_args(
        ["--state-file", str(tmp_path / "seen.json"), "--only-new"])
    state = SeenJobs.load(args.state_file)
    first = collect_mode(FakeClient(offers, details), PROFILE, "werkstudent", args, state)
    assert len(first["recommended"]) == 1
    second = collect_mode(FakeClient(offers, details), PROFILE, "werkstudent", args, state)
    assert second["recommended"] == []
    assert any("--only-new" in j["reason"] for j in second["rejected"])


# -------------------------------------------------------------------- Report

def test_report_renders_german_sections():
    ctx = {
        "wo": "Regensburg", "umkreis": 50, "days": 30, "min_match": 60,
        "generated": "2026-07-02",
        "candidate": PROFILE["candidate"],
        "sections": [{
            "mode": "werkstudent",
            "recommended": [{
                "rank": 1, "refnr": "12345-X", "title": "Werkstudent IoT",
                "employer": "Testfirma GmbH", "ort": "93053 Regensburg",
                "published": "2026-07-01", "eintritt": "", "percent": 85,
                "new": True, "externe_url": "",
                "active": [{"label": "Python", "coverage": "voll",
                            "evidence": "Python produktiv", "hits": ["python"]}],
            }],
            "rejected": [{"title": "Kellner", "employer": "Gasthaus", "ort": "Regensburg",
                          "published": "2026-07-01", "reason": "Zieldomäne"}],
            "stats": {"queries": ["Werkstudent"], "found": 2, "detailed": 1},
        }],
    }
    md = render_report(ctx)
    assert "## Kandidatenprofil" in md
    assert "Empfohlene Treffer" in md
    assert "arbeitsagentur.de/jobsuche/jobdetail/12345-X" in md
    assert "Match ≈ 85 %" in md and "🆕" in md
    assert "Quellen-Abdeckung" in md
    assert "20 Std./Woche" in md
    assert "02.07.2026" in md  # deutsches Datumsformat
