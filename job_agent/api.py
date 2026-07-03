"""Client für die offizielle Jobsuche-API der Bundesagentur für Arbeit.

Community-Dokumentation: https://github.com/bundesAPI/jobsuche-api
Der Standard-Key ist der öffentliche Key der Jobsuche-Webanwendung der BA —
kein Scraping, kein Umgehen von Zugriffsschutz. Sollte der Key rotiert
werden, kann über die Umgebungsvariable JOBSUCHE_API_KEY ein neuer gesetzt
werden.
"""

import base64
import os
import time

import requests

BASE_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4"
PUBLIC_API_KEY = "jobboerse-jobsuche"
USER_AGENT = "calculator-ci-cd-job-agent (persoenliche Jobsuche)"
JOBDETAIL_WEB_URL = "https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}"


class JobsucheAuthError(RuntimeError):
    """401/403 von der API — vermutlich wurde der öffentliche Key rotiert."""


def encode_refnr(refnr: str) -> str:
    """Referenznummer wie von der Jobsuche-Webanwendung base64url-kodieren."""
    return base64.urlsafe_b64encode(refnr.encode("utf-8")).decode("ascii")


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

    def _get(self, path, params=None):
        url = f"{BASE_URL}/{path}"
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
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            if resp.status_code in (401, 403):
                raise JobsucheAuthError(
                    f"HTTP {resp.status_code} von der Jobsuche-API. Der öffentliche "
                    "API-Key wurde vermutlich rotiert — aktuellen Key unter "
                    "https://github.com/bundesAPI/jobsuche-api nachschlagen und als "
                    "Umgebungsvariable JOBSUCHE_API_KEY setzen."
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = RuntimeError(f"HTTP {resp.status_code} für {url}")
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(
            f"Jobsuche-API nach {self.max_retries + 1} Versuchen nicht erreichbar: {last_error}"
        )

    def search(self, was=None, wo=None, umkreis=None, arbeitszeit=None,
               veroeffentlichtseit=None, angebotsart=1, max_results=200):
        """Stellenangebote suchen; paginiert und nach refnr dedupliziert."""
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
            data = self._get("jobs", params)
            offers = data.get("stellenangebote") or []
            if not offers:
                break
            for offer in offers:
                refnr = offer.get("refnr")
                if refnr and refnr not in seen:
                    seen.add(refnr)
                    results.append(offer)
            if len(offers) < size:
                break
            page += 1
        return results[:max_results]

    def job_details(self, refnr):
        """Volltext-Details (inkl. Stellenbeschreibung) zu einer Referenznummer."""
        return self._get(f"jobdetails/{encode_refnr(refnr)}")
