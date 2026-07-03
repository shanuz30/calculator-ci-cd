"""Job-Agent für die Jobsuche der Bundesagentur für Arbeit.

Sucht Werkstudenten- und Vollzeitstellen über die offizielle Jobsuche-API
(https://github.com/bundesAPI/jobsuche-api) und erzeugt einen deutschen
Markdown-Report mit JD-Match-Bewertung gegen das Kandidatenprofil.
"""

__all__ = ["api", "scoring", "state", "report", "cli"]
