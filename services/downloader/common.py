"""Funzioni comuni: configurazione, richieste HTTP, cartella di output, report.csv."""

import csv
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("downloader")

REPORT_COLONNE = ["sha256", "url", "data_ora_download", "file", "layer",
                  "start_index", "record", "byte", "http_status"]


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
def carica_env(percorso: Path) -> None:
    """Legge un file .env (righe CHIAVE=valore) e imposta le variabili non già definite."""
    if not percorso.is_file():
        return
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#") or "=" not in riga:
            continue
        chiave, valore = riga.split("=", 1)
        os.environ.setdefault(chiave.strip(), valore.strip().strip('"').strip("'"))


def env_str(nome: str, default: str) -> str:
    valore = os.environ.get(nome, "").strip()
    return valore if valore else default


def env_int(nome: str, default: int) -> int:
    return int(env_str(nome, str(default)))


def env_lista(nome: str, default: str) -> list[str]:
    return [v.strip() for v in env_str(nome, default).split(",") if v.strip()]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def nuova_sessione(user_agent: str) -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = user_agent
    return s


def scarica(session: requests.Session, url: str, tentativi: int, timeout: int) -> requests.Response:
    """GET con nuovi tentativi in caso di errore (attese 2, 4, 8 s...)."""
    for tentativo in range(1, tentativi + 1):
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentativo == tentativi:
                raise
            attesa = 2 ** tentativo
            log.warning("Tentativo %d/%d fallito (%s). Nuovo tentativo tra %d s",
                        tentativo, tentativi, e, attesa)
            time.sleep(attesa)


# ---------------------------------------------------------------------------
# File di output
# ---------------------------------------------------------------------------
def cartella_del_giorno(radice: Path, portale: str, adesso: datetime) -> Path:
    """Restituisce (e crea) <radice>/<portale>/AAAA-MM-GG/."""
    cartella = radice / portale / adesso.strftime("%Y-%m-%d")
    cartella.mkdir(parents=True, exist_ok=True)
    return cartella


def percorso_libero(cartella: Path, nome: str, ora_esecuzione: str) -> Path:
    """Percorso che non sovrascrive file esistenti: se il nome è già usato aggiunge _HHMMSS."""
    p = cartella / nome
    if not p.exists():
        return p
    base, est = Path(nome).stem, Path(nome).suffix
    p = cartella / f"{base}_{ora_esecuzione}{est}"
    n = 2
    while p.exists():
        p = cartella / f"{base}_{ora_esecuzione}_{n}{est}"
        n += 1
    return p


class Report:
    """report.csv della cartella del giorno: creato se manca, altrimenti le righe si aggiungono in fondo."""

    def __init__(self, percorso: Path):
        self.percorso = percorso
        nuovo = not percorso.exists()
        self._fh = open(percorso, "a", encoding="utf-8", newline="")
        self._w = csv.writer(self._fh, delimiter=";")
        if nuovo:
            self._w.writerow(REPORT_COLONNE)

    def aggiungi(self, **riga) -> None:
        self._w.writerow([riga.get(c, "") for c in REPORT_COLONNE])
        self._fh.flush()

    def chiudi(self) -> None:
        self._fh.close()
