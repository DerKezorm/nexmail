"""Der Healthcheck.

Bewusst ohne Anmeldung und ohne Datenbankzugriff: Er beantwortet die Frage
"laeuft der Prozess und nimmt er Anfragen an". Wer ihn an die Datenbank
haengt, bekommt bei einer langsamen Platte einen neu startenden Container.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__

router = APIRouter(prefix="/api", tags=["health"])


class Gesundheit(BaseModel):
    status: str
    version: str


@router.get("/health", response_model=Gesundheit)
def health() -> Gesundheit:
    return Gesundheit(status="ok", version=__version__)
