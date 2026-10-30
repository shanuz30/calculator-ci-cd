"""Client für die offizielle Jobsuche-API der Bundesagentur für Arbeit.

Dokumentation: https://jobsuche.api.bund.dev/ · https://github.com/bundesAPI/jobsuche-api
Der Standard-Key ist der öffentliche Key der Jobsuche-Webanwendung der BA —
kein Scraping, kein Umgehen von Zugriffsschutz. Sollte der Key rotiert
werden, kann über die Umgebungsvariable JOBSUCHE_API_KEY ein neuer gesetzt
werden.

Endpunkte (geprüft 2026-10-30):
  Suche:   GET {SERVICE_URL}/pc/v6/jobs                 (pc/v4/jobs ist abgeschaltet)
  Details: GET {SERVICE_URL}/pc/v4/jobdetails/{base64(referenznummer)}

Das v6-Suchformat unterscheidet sich vom alten v4-Format (``ergebnisliste``,
``referenznummer``, ``stellenangebotsTitel``, ``firma``, ``stellenlokationen``).
``normalize_search_item`` bildet es auf die Feldnamen ab, die Pipeline und
Report seit jeher lesen (``refnr``, ``titel``, ``arbeitgeber`` …).
"""

import base64
import os
import time
from urllib.parse import quote

import requests

SERVICE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
SEARCH_URL = f"{SERVICE_URL}/pc/v6/jobs"
DETAILS_URL = f"{SERVICE_URL}/pc/v4/jobdetails"
PUBLIC_API_KEY = "jobboerse-jobsuche"
USER_AGENT = "calculator-ci-cd-job-agent (persoenliche Jobsuche)"
JOBDETAIL_WEB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"

# Begründungstext des BA-API-Gateways, wenn für den Pfad keine Route existiert.
# Dasselbe Gateway antwortet bei fehlendem/falschem Key mit "403 Forbidden".
GATEWAY_NO_ROUTE_REASON = "no match found for request"


class JobsucheAuthError(RuntimeError):
    """403/401 "Forbidden" — API-Key fehlt, ist falsch oder wurde rotiert."""


class JobsucheEndpointError(RuntimeError):
    """403 "No match found for request" — das Gateway kennt den Pfad nicht
    (Endpunkt verschoben/abgeschaltet). Kein Key-Problem."""


class JobsucheNotFoundError(RuntimeError):
    """404 — Route existiert, aber die Stellenanzeige nicht (mehr)."""


def encode_refnr(refnr: str) -> str:
    """Referenznummer für den Detail-Pfad kodieren: Standard-Base64 (wie
    dokumentiert), danach als Pfadsegment prozentkodiert. Ein rohes "/" aus
    dem Base64-Alphabet würde sonst den Pfad zerteilen (Gateway: "No match"),
    "+" und "=" werden ebenfalls kodiert. Bei allen bisher gesehenen
    Referenznummern entsteht weder "+" noch "/"."""
    encoded = base64.b64encode(refnr.encode("utf-8")).decode("ascii")
    return quote(encoded, safe="")


def _first(*values):
    for value in values:
        if value:
            return value
    return ""


def _http_url(value):
    """Nur echte http(s)-Links übernehmen — nichts zusammenbauen oder raten."""
    if isinstance(value, str):
        value = value.strip()
        if value.lower().startswith(("http://", "https://")):
            return value
    return ""


def external_application_url(record):
    """Externer Link aus Such- oder Detail-Antwort; "" wenn keiner geliefert
    wird. Die API schreibt ``externeURL``; ``externeUrl`` wird als Fallback
    gelesen, weil ältere Versionen/Dokumentation diese Schreibweise nutzen.

    Achtung: Der Link zeigt oft auf eine Jobbörse (jobvector, get-in-engineering
    …), nicht zwingend auf die Bewerbungsseite des Arbeitgebers."""
    record = record or {}
    return _http_url(record.get("externeURL")) or _http_url(record.get("externeUrl"))


def normalize_search_item(item):
    """v6-Suchtreffer → Feldnamen der bestehenden Pipeline.

    Zusätzlich: ``externe_url``, ``weitere_arbeitsorte`` (Anzahl weiterer
    Standorte) und ``raw`` (Originaldatensatz)."""
    locations = item.get("stellenlokationen") or []
    address = (locations[0].get("adresse") or {}) if locations else {}
    return {
        "refnr": item.get("referenznummer") or "",
        "titel": item.get("stellenangebotsTitel") or "",
        "beruf": item.get("hauptberuf") or "",
        "arbeitgeber": item.get("firma") or "",
        "arbeitsort": {"plz": address.get("plz") or "", "ort": address.get("ort") or ""},
        "weitere_arbeitsorte": max(len(locations) - 1, 0),
        "aktuelleVeroeffentlichungsdatum": _first(
            (item.get("veroeffentlichungszeitraum") or {}).get("von"),
            item.get("datumErsteVeroeffentlichung"),
        ),
        "eintrittsdatum": (item.get("eintrittszeitraum") or {}).get("von") or "",
        "externe_url": external_application_url(item),
        "raw": item,
    }


class JobsucheClient:
    def __init__(self, api_key=None, session=None, delay_seconds=1.0, max_retries=3,
                 backoff_seconds=2.0):
        self.api_key = api_key or os.environ.get("JOBSUCHE_API_KEY") or PUBLIC_API_KEY
        self.session = session or requests.Session()
        self.delay_seconds = delay_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._last_request_ts = 0.0

    def _throttle(self):
        wait = self._last_request_ts + self.delay_seconds - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request_ts = time.monotonic()

    def _get(self, url, params=None):
        headers = {
            "X-API-Key": self.api_key,
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        last_error = None
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=30)
            except requests.exceptions.ProxyError as exc:
                last_error = f"Proxy-Fehler (Anfrage hat die BA nicht erreicht): {exc}"
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            except requests.RequestException as exc:
                last_error = f"Netzwerkfehler: {exc}"
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            reason = (getattr(resp, "reason", "") or "").strip()
            if resp.status_code == 403 and reason.lower() == GATEWAY_NO_ROUTE_REASON:
                raise JobsucheEndpointError(
                    f"HTTP 403 '{reason}' für {url}: Das BA-Gateway kennt diesen Pfad "
                    "nicht (Endpunkt verschoben/abgeschaltet) — kein Key-Problem. "
                    "Aktuelle Pfade unter https://jobsuche.api.bund.dev/ prüfen."
                )
            if resp.status_code in (401, 403):
                raise JobsucheAuthError(
                    f"HTTP {resp.status_code} '{reason}' von der Jobsuche-API. Der "
                    "API-Key fehlt oder wurde rotiert — aktuellen Key unter "
                    "https://github.com/bundesAPI/jobsuche-api nachschlagen und als "
                    "Umgebungsvariable JOBSUCHE_API_KEY setzen."
                )
            if resp.status_code == 404:
                raise JobsucheNotFoundError(f"HTTP 404 für {url} (Anzeige nicht gefunden)")
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code} für {url}"
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(
            f"Jobsuche-API nach {self.max_retries + 1} Versuchen nicht erreichbar: {last_error}"
        )

    def search(self, was=None, wo=None, umkreis=None, arbeitszeit=None,
               veroeffentlichtseit=None, angebotsart=1, max_results=200):
        """Stellenangebote suchen (v6); paginiert, nach Referenznummer
        dedupliziert, normalisiert (siehe ``normalize_search_item``).

        Hinweis: v6 ignoriert ``veroeffentlichtseit`` (geprüft 2026-10-30) —
        der Parameter wird trotzdem gesendet; das Datumsfenster prüft die
        Pipeline clientseitig."""
        results = []
        seen = set()
        page, size = 1, 100
        while len(results) < max_results:
            params = {"page": page, "size": size, "angebotsart": angebotsart}
            if was:
                params["was"] = was
            if wo:
                params["wo"] = wo
            if umkreis:
                params["umkreis"] = umkreis
            if arbeitszeit:
                params["arbeitszeit"] = arbeitszeit
            if veroeffentlichtseit:
                params["veroeffentlichtseit"] = veroeffentlichtseit
            data = self._get(SEARCH_URL, params)
            items = data.get("ergebnisliste") or []
            if not items:
                break
            for item in items:
                offer = normalize_search_item(item)
                if offer["refnr"] and offer["refnr"] not in seen:
                    seen.add(offer["refnr"])
                    results.append(offer)
            total = data.get("maxErgebnisse")
            if len(items) < size or (isinstance(total, int) and page * size >= total):
                break
            page += 1
        return results[:max_results]

    def job_details(self, refnr):
        """Volltext-Details (inkl. Stellenbeschreibung) zu einer Referenznummer.
        Antwort unverändert; Link über ``external_application_url`` lesen."""
        return self._get(f"{DETAILS_URL}/{encode_refnr(refnr)}")
