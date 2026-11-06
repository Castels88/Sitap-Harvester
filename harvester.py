"""
Harvester SITAP - Vincoli paesaggistici L.1497/39 (punti, linee, poligoni)

Cosa fa, in breve:
  1. chiede al servizio WFS di SITAP i dati, una pagina da 500 record alla volta;
  2. salva ogni pagina così com'è arrivata (file JSON "grezzo") in  <portale>/<AAAA-MM-GG>/ ;
  3. per ogni file scritto aggiunge una riga a  <portale>/<AAAA-MM-GG>/report.csv
     con hash SHA-256, URL e data/ora del download;
  4. alla fine controlla che i record scaricati siano tanti quanti dichiara il server.

Uso:
  python harvester.py                 # scarica i 3 layer nella cartella corrente
  python harvester.py --output D:\\dati # sceglie la cartella radice
  python harvester.py --layers pun    # solo i punti (pun, lin, pol)
"""

import argparse
import csv
import hashlib
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------
PORTALE = "sitap"                                  # nome-portale nel percorso dei file
WFS_URL = "https://sitap.cultura.gov.it/geoserver/wfs"
LAYERS = {                                         # sigla -> nome del layer sul server
    "pun": "sitap_wfs_ws:wms_ext_sitap_v1497_pun",  # vincoli puntuali
    "lin": "sitap_wfs_ws:wms_ext_sitap_v1497_lin",  # vincoli lineari
    "pol": "sitap_wfs_ws:wms_ext_sitap_v1497_pol",  # vincoli poligonali
}
PAGE_SIZE = 500          # record per pagina (count)
PAUSA_SECONDI = 0.5      # attesa tra una richiesta e l'altra, per non sovraccaricare il server
TENTATIVI = 4            # quante volte riprovare se una richiesta fallisce
TIMEOUT = 180            # secondi massimi di attesa per una risposta
USER_AGENT = "sitap-harvester/1.0 (python-requests)"
REPORT_COLONNE = ["sha256", "url", "data_ora_download", "file", "layer",
                  "start_index", "record", "byte", "http_status"]

log = logging.getLogger("harvester")


# ---------------------------------------------------------------------------
# Funzioni di supporto
# ---------------------------------------------------------------------------
def url_pagina(layer: str, start_index: int) -> str:
    """Costruisce l'URL della chiamata WFS per una pagina."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "sortBy": "gid",            # obbligatorio: senza ordinamento il server risponde 400
        "count": PAGE_SIZE,
        "startIndex": start_index,
    }
    return f"{WFS_URL}?{urlencode(params, safe=':/')}"


def scarica(session: requests.Session, url: str) -> requests.Response:
    """Scarica un URL riprovando in caso di errore (attese crescenti: 2, 4, 8 s...)."""
    for tentativo in range(1, TENTATIVI + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if tentativo == TENTATIVI:
                raise
            attesa = 2 ** tentativo
            log.warning("Tentativo %d fallito (%s). Riprovo tra %d s", tentativo, e, attesa)
            time.sleep(attesa)


def percorso_libero(cartella: Path, nome: str, ora_esecuzione: str) -> Path:
    """Restituisce un percorso che non sovrascrive file già presenti.
    Se il file esiste già (seconda esecuzione nello stesso giorno) aggiunge l'ora: nome_HHMMSS.json"""
    p = cartella / nome
    if not p.exists():
        return p
    p = cartella / f"{Path(nome).stem}_{ora_esecuzione}{Path(nome).suffix}"
    n = 2
    while p.exists():
        p = cartella / f"{Path(nome).stem}_{ora_esecuzione}_{n}{Path(nome).suffix}"
        n += 1
    return p


class Report:
    """Gestisce report.csv: lo crea se non c'è, altrimenti aggiunge righe in fondo (mai sovrascrive)."""

    def __init__(self, percorso: Path):
        self.percorso = percorso
        nuovo = not percorso.exists()
        self.fh = open(percorso, "a", encoding="utf-8", newline="")
        self.w = csv.writer(self.fh, delimiter=";")
        if nuovo:
            self.w.writerow(REPORT_COLONNE)

    def aggiungi(self, **riga):
        self.w.writerow([riga.get(c, "") for c in REPORT_COLONNE])
        self.fh.flush()   # scrive subito su disco: se il programma si ferma, le righe restano

    def chiudi(self):
        self.fh.close()


# ---------------------------------------------------------------------------
# Harvesting di un layer
# ---------------------------------------------------------------------------
def harvest_layer(session, sigla, layer, cartella, report, ora_esecuzione):
    """Scarica tutte le pagine di un layer. Restituisce (record attesi, gid unici scaricati, file scritti)."""
    nome_breve = layer.split(":")[-1]
    start, attesi, gid_visti, file_scritti = 0, None, set(), 0

    while True:
        url = url_pagina(layer, start)
        r = scarica(session, url)
        data_ora = datetime.now().astimezone().isoformat(timespec="seconds")
        contenuto = r.content                      # byte esatti ricevuti dal server
        sha256 = hashlib.sha256(contenuto).hexdigest()

        dati = json.loads(contenuto)               # controlla anche che sia JSON valido
        features = dati.get("features", [])
        if attesi is None:
            attesi = dati.get("numberMatched")
            log.info("[%s] il server dichiara %s record", sigla, attesi)

        nome_file = f"{nome_breve}_{start:05d}.json"
        destinazione = percorso_libero(cartella, nome_file, ora_esecuzione)
        destinazione.write_bytes(contenuto)        # salvo il file grezzo, senza modifiche
        file_scritti += 1

        report.aggiungi(sha256=sha256, url=url, data_ora_download=data_ora,
                        file=destinazione.name, layer=layer, start_index=start,
                        record=len(features), byte=len(contenuto), http_status=r.status_code)

        gid_visti.update(f["properties"]["gid"] for f in features)
        log.info("[%s] pagina startIndex=%d: %d record -> %s", sigla, start, len(features), destinazione.name)

        if len(features) < PAGE_SIZE:              # ultima pagina
            break
        start += PAGE_SIZE
        time.sleep(PAUSA_SECONDI)

    return attesi, len(gid_visti), file_scritti


# ---------------------------------------------------------------------------
# Programma principale
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Harvester SITAP vincoli paesaggistici L.1497/39")
    ap.add_argument("--output", default=".", help="cartella radice (default: cartella corrente)")
    ap.add_argument("--layers", nargs="+", choices=list(LAYERS), default=list(LAYERS),
                    help="layer da scaricare: pun lin pol (default: tutti)")
    args = ap.parse_args()

    adesso = datetime.now().astimezone()
    cartella = Path(args.output) / PORTALE / adesso.strftime("%Y-%m-%d")
    cartella.mkdir(parents=True, exist_ok=True)
    ora_esecuzione = adesso.strftime("%H%M%S")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(cartella / "harvest.log", encoding="utf-8")],
    )
    log.info("Inizio harvesting. Cartella: %s", cartella.resolve())

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    report = Report(cartella / "report.csv")

    esito_ok = True
    try:
        for sigla in args.layers:
            attesi, scaricati, n_file = harvest_layer(session, sigla, LAYERS[sigla], cartella,
                                                      report, ora_esecuzione)
            ok = attesi == scaricati
            esito_ok &= ok
            log.info("[%s] FINE: %d file, %d record unici, attesi %s -> %s",
                     sigla, n_file, scaricati, attesi, "OK" if ok else "ATTENZIONE: NON CORRISPONDE")
    except Exception:
        log.exception("Harvesting interrotto da un errore")
        esito_ok = False
    finally:
        report.chiudi()

    log.info("Report: %s", (cartella / "report.csv").resolve())
    log.info("Esito complessivo: %s", "OK" if esito_ok else "CON ERRORI")
    sys.exit(0 if esito_ok else 1)


if __name__ == "__main__":
    main()
