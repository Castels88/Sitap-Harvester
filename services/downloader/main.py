"""Downloader SITAP: orchestrazione.

Legge la configurazione dalle variabili d'ambiente (o dal file .env nella radice del progetto),
scarica i layer richiesti con sitap.py e scrive file grezzi e report.csv in <OUTPUT_DIR>/sitap/AAAA-MM-GG/.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

import sitap
from common import Report, carica_env, cartella_del_giorno, env_int, env_lista, env_str, nuova_sessione

PORTALE = "sitap"
USER_AGENT = "sitap-harvester/1.0 (python-requests)"
RADICE_PROGETTO = Path(__file__).resolve().parents[2]


def main() -> int:
    carica_env(Path.cwd() / ".env")
    carica_env(RADICE_PROGETTO / ".env")

    layers = env_lista("LAYERS", "pun,lin,pol")
    sconosciuti = [l for l in layers if l not in sitap.LAYERS]
    cfg = {
        "page_size": env_int("PAGE_SIZE", 500),
        "max_records": env_int("MAX_RECORDS", 0),
        "tentativi": env_int("HTTP_RETRIES", 5),
        "timeout": env_int("HTTP_TIMEOUT", 180),
        "pausa": float(env_str("PAUSE_SECONDS", "0.5")),
    }

    adesso = datetime.now().astimezone()
    cartella = cartella_del_giorno(Path(env_str("OUTPUT_DIR", ".")), PORTALE, adesso)
    ora_esecuzione = adesso.strftime("%H%M%S")

    logging.basicConfig(
        level=env_str("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(cartella / "harvest.log", encoding="utf-8")],
    )
    log = logging.getLogger("downloader")
    if sconosciuti:
        log.error("LAYERS non validi: %s (ammessi: %s)", sconosciuti, ", ".join(sitap.LAYERS))
        return 1

    log.info("Inizio download. Layer: %s. Cartella: %s", ", ".join(layers), cartella.resolve())
    if cfg["max_records"]:
        log.warning("MAX_RECORDS=%d: download parziale, solo per prove", cfg["max_records"])

    session = nuova_sessione(USER_AGENT)
    report = Report(cartella / "report.csv")
    esito_ok = True
    try:
        for sigla in layers:
            try:
                r = sitap.scarica_layer(session, sigla, cartella, report, ora_esecuzione, cfg)
            except Exception:
                log.exception("[%s] download fallito", sigla)
                esito_ok = False
                continue
            esito_ok &= r["ok"]
            log.info("[%s] FINE: %d file, %d record unici, attesi %s -> %s", sigla, r["file"],
                     r["scaricati"], r["attesi"], "OK" if r["ok"] else "ATTENZIONE: NON CORRISPONDE")
    finally:
        report.chiudi()

    log.info("Report: %s", report.percorso.resolve())
    log.info("Esito complessivo: %s", "OK" if esito_ok else "CON ERRORI")
    return 0 if esito_ok else 1


if __name__ == "__main__":
    sys.exit(main())
