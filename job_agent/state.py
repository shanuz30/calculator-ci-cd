"""Merkt sich bereits gesehene Stellen (refnr), damit geplante Läufe nur
neue Treffer hervorheben. Bewusst eine flache JSON-Datei im Repo — der
wöchentliche GitHub-Actions-Lauf committet sie zusammen mit dem Report."""

import json
from datetime import date
from pathlib import Path

DEFAULT_STATE_PATH = Path("docs/job-search/.seen_jobs.json")


class SeenJobs:
    def __init__(self, path=None):
        self.path = Path(path) if path else DEFAULT_STATE_PATH
        self._jobs = {}

    @classmethod
    def load(cls, path=None):
        state = cls(path)
        if state.path.exists():
            with open(state.path, encoding="utf-8") as fh:
                state._jobs = json.load(fh)
        return state

    def is_new(self, refnr):
        return refnr not in self._jobs

    def mark_seen(self, refnr, title="", employer=""):
        if refnr not in self._jobs:
            self._jobs[refnr] = {
                "first_seen": date.today().isoformat(),
                "title": title,
                "employer": employer,
            }

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._jobs, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")

    def __len__(self):
        return len(self._jobs)
