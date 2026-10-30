# -*- coding: utf-8 -*-
"""Tests für den Job-Agenten — komplett ohne Netzwerkzugriff (Fake-Session)."""

import base64
import json
from pathlib import Path
from urllib.parse import unquote

import pytest

from job_agent.api import (JobsucheAuthError, JobsucheClient, JobsucheEndpointError,
                           JobsucheNotFoundError, encode_refnr, external_application_url,
                           normalize_search_item)
from job_agent.cli import _offer_meta, build_arg_parser, collect_mode
from job_agent.report import render_report
from job_agent.scoring import (is_ausbildung_or_praktikum, is_senior_role,
                               is_werkstudent, keyword_in_text, load_profile,
                               score_job, title_prescreen)
from job_agent.state import SeenJobs

PROFILE = load_profile()
FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, reason=""):
        self.status_code = status_code
        self.reason = reason
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
# Fixtures: gekürzte echte Antworten von pc/v6/jobs und pc/v4/jobdetails (2026-10-30).

def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _search_page(refs):
    """Minimale v6-Suchseite mit den gegebenen Referenznummern."""
    return {"ergebnisliste": [{"referenznummer": r, "stellenangebotsTitel": r} for r in refs],
            "maxErgebnisse": len(refs), "page": 1, "size": 100}


def test_encode_refnr_is_standard_base64_and_path_safe():
    refnr = "12465-1648533-1-S"
    assert encode_refnr(refnr) == "MTI0NjUtMTY0ODUzMy0xLVM%3D"   # "=" prozentkodiert
    assert base64.b64decode(unquote(encode_refnr(refnr))).decode() == refnr
    # Standard-Alphabet erzeugt "/" und "+" — beide müssen kodiert werden,
    # ein rohes "/" trifft beim Gateway keine Route mehr.
    assert encode_refnr("???") == "Pz8%2F"
    assert encode_refnr("~~~") == "fn5%2B"


def test_search_parses_v6_fixture():
    client = make_client([FakeResponse(payload=_fixture("ba_v6_jobs_search.json"))])
    offers = client.search(was="Ingenieur", wo="Regensburg", umkreis=50)

    call = client.session.calls[0]
    assert call["url"] == "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v6/jobs"
    assert call["headers"]["X-API-Key"] == "jobboerse-jobsuche"
    assert call["params"]["was"] == "Ingenieur" and call["params"]["umkreis"] == 50

    assert [o["refnr"] for o in offers] == [
        "14225-94f87ca4d9b5fe73-S", "13645-250885-S", "10001-1001395800-S"]
    first, multi, no_plz = offers
    assert first["titel"] == "Ingenieur, Techniker - SPS-Programmierer (m/w/d)"
    assert first["arbeitgeber"] == "Ingenieurbüro Guttenberger"
    assert first["beruf"] == "Ingenieur/in - Elektrotechnik"
    assert first["arbeitsort"] == {"plz": "93047", "ort": "Regensburg"}
    assert first["aktuelleVeroeffentlichungsdatum"] == "2026-10-27"
    assert first["eintrittsdatum"] == "2026-10-28"
    assert first["externe_url"].startswith("https://www.jobvector.de/job/ingenieur-94f87ca4d9b5fe73/")
    assert first["raw"]["referenznummer"] == first["refnr"]
    assert multi["weitere_arbeitsorte"] == 2
    assert no_plz["arbeitsort"] == {"plz": "", "ort": "Regensburg"}
    assert no_plz["externe_url"] == ""             # nicht geliefert → nicht erfunden


def test_normalized_offer_feeds_existing_pipeline_meta():
    item = _fixture("ba_v6_jobs_search.json")["ergebnisliste"][0]
    meta = _offer_meta(normalize_search_item(item))
    assert meta == {
        "refnr": "14225-94f87ca4d9b5fe73-S",
        "title": "Ingenieur, Techniker - SPS-Programmierer (m/w/d)",
        "beruf": "Ingenieur/in - Elektrotechnik",
        "employer": "Ingenieurbüro Guttenberger",
        "ort": "93047 Regensburg",
        "published": "2026-10-27",
        "eintritt": "2026-10-28",
    }


def test_search_stops_on_short_page_and_dedupes():
    client = make_client([FakeResponse(payload=_search_page(["A", "B", "A"]))])
    result = client.search(was="Werkstudent", wo="Regensburg", umkreis=50)
    assert [o["refnr"] for o in result] == ["A", "B"]
    assert len(client.session.calls) == 1


def test_search_paginates_until_max_results():
    page1 = _search_page([f"R{i}" for i in range(100)])
    page1["maxErgebnisse"] = 102
    page2 = _search_page(["R100", "R101"])
    client = make_client([FakeResponse(payload=page1), FakeResponse(payload=page2)])
    result = client.search(was="x", max_results=150)
    assert len(result) == 102
    assert [c["params"]["page"] for c in client.session.calls] == [1, 2]


def test_search_stops_at_max_ergebnisse_without_extra_request():
    page1 = _search_page([f"R{i}" for i in range(100)])
    page1["maxErgebnisse"] = 100
    client = make_client([FakeResponse(payload=page1)])
    assert len(client.search(was="x")) == 100
    assert len(client.session.calls) == 1


def test_job_details_uses_v4_path_and_encoded_refnr():
    fixture = _fixture("ba_v4_jobdetails_external_url.json")
    client = make_client([FakeResponse(payload=fixture)])
    details = client.job_details("19192-250903-17898145-S")
    assert client.session.calls[0]["url"] == (
        "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobdetails/"
        "MTkxOTItMjUwOTAzLTE3ODk4MTQ1LVM%3D")
    assert client.session.calls[0]["headers"]["X-API-Key"] == "jobboerse-jobsuche"
    assert details["stellenangebotsTitel"].startswith("Bauleiter:in")
    assert details["stellenangebotsBeschreibung"]
    assert external_application_url(details).startswith("https://baugpt.com/jobs/")


def test_details_fixtures_without_link_and_staffing_flags():
    agency = _fixture("ba_v4_jobdetails_staffing_agency.json")
    absent = _fixture("ba_v4_jobdetails_flags_absent.json")
    assert external_application_url(agency) == ""
    assert external_application_url(absent) == ""
    # Rohdaten bleiben unverändert für die spätere Direkt/Personaldienstleister-Einordnung
    assert agency["istArbeitnehmerUeberlassung"] is True
    assert "istArbeitnehmerUeberlassung" not in absent


def test_external_url_spellings_and_rejects_non_links():
    assert external_application_url({"externeURL": " https://a.example/job "}) == "https://a.example/job"
    assert external_application_url({"externeUrl": "https://b.example/job"}) == "https://b.example/job"
    assert external_application_url({"externeURL": "www.c.example"}) == ""
    assert external_application_url({"externeURL": None}) == ""
    assert external_application_url({}) == ""
    assert external_application_url(None) == ""


def test_403_forbidden_is_auth_error():
    client = make_client([FakeResponse(status_code=403, reason="Forbidden")])
    with pytest.raises(JobsucheAuthError, match="JOBSUCHE_API_KEY"):
        client.search(was="x")


def test_403_no_route_is_endpoint_error_not_auth():
    client = make_client([FakeResponse(status_code=403, reason="No match found for request")])
    with pytest.raises(JobsucheEndpointError, match="Pfad") as exc:
        client.search(was="x")
    assert not isinstance(exc.value, JobsucheAuthError)


def test_404_details_is_not_found_error():
    client = make_client([FakeResponse(status_code=404, payload={
        "messages": [{"code": "STELLENANGEBOT_NICHT_GEFUNDEN"}]})])
    with pytest.raises(JobsucheNotFoundError):
        client.job_details("99999-x-S")


def test_proxy_error_is_retried_and_reported():
    import requests

    class ProxySession(FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append({"url": url})
            raise requests.exceptions.ProxyError("407 Proxy Authentication Required")

    client = JobsucheClient(session=ProxySession([]), delay_seconds=0,
                            backoff_seconds=0, max_retries=1)
    with pytest.raises(RuntimeError, match="Proxy-Fehler"):
        client.search(was="x")
    assert len(client.session.calls) == 2


def test_server_error_is_retried_then_succeeds():
    client = make_client([
        FakeResponse(status_code=500),
        FakeResponse(payload=_search_page(["A"])),
    ])
    assert client.search(was="x")[0]["refnr"] == "A"
    assert len(client.session.calls) == 2


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


def test_collect_mode_takes_externe_url_from_real_detail_field(tmp_path):
    # Regression: Details liefern "externeURL"; früher wurde "externeUrl" gelesen → Link fehlte.
    detail = dict(_fixture("ba_v4_jobdetails_external_url.json"),
                  stellenangebotsBeschreibung="Python, MQTT, IoT, Git, Linux, Docker, "
                                              "Elektrotechnik-Studium, gute Deutschkenntnisse.")
    offers = [_offer("GOOD", "Werkstudent Softwareentwicklung Python (m/w/d)")]
    args = build_arg_parser().parse_args(["--state-file", str(tmp_path / "seen.json")])
    section = collect_mode(FakeClient(offers, {"GOOD": detail}), PROFILE, "werkstudent",
                           args, SeenJobs.load(args.state_file))
    assert section["recommended"][0]["externe_url"] == detail["externeURL"]
    assert "Externe Bewerbungsseite" in render_report({
        "wo": "Regensburg", "umkreis": 50, "days": 30, "min_match": 60,
        "generated": "2026-10-30", "candidate": PROFILE["candidate"],
        "sections": [section]})


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
