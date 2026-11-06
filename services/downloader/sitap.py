"""Fonte SITAP: vincoli paesaggistici L.1497/39 dal WFS pubblico del Ministero della Cultura."""

import hashlib
import json
import logging
import time
from datetime import datetime
from urllib.parse import urlencode

from common import percorso_libero, scarica

log = logging.getLogger("downloader")

WFS_URL = "https://sitap.cultura.gov.it/geoserver/wfs"
LAYERS = {
    "pun": "sitap_wfs_ws:wms_ext_sitap_v1497_pun",   # vincoli puntuali
    "lin": "sitap_wfs_ws:wms_ext_sitap_v1497_lin",   # vincoli lineari
    "pol": "sitap_wfs_ws:wms_ext_sitap_v1497_pol",   # vincoli poligonali
}


def url_pagina(layer: str, start_index: int, page_size: int) -> str:
    """URL GetFeature di una pagina. sortBy=gid è obbligatorio: senza, il server risponde 400."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": layer,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "sortBy": "gid",
        "count": page_size,
        "startIndex": start_index,
    }
    return f"{WFS_URL}?{urlencode(params, safe=':/')}"


def scarica_layer(session, sigla, cartella, report, ora_esecuzione, cfg) -> dict:
    """Scarica tutte le pagine di un layer, salva i file grezzi e scrive il report.
    Restituisce un riepilogo con record attesi e scaricati."""
    layer = LAYERS[sigla]
    nome_breve = layer.split(":")[-1]
    page_size, max_records = cfg["page_size"], cfg["max_records"]
    start, attesi, gid_visti, file_scritti = 0, None, set(), 0

    while True:
        conteggio = page_size if not max_records else min(page_size, max_records - start)
        url = url_pagina(layer, start, conteggio)
        r = scarica(session, url, cfg["tentativi"], cfg["timeout"])
        data_ora = datetime.now().astimezone().isoformat(timespec="seconds")
        contenuto = r.content
        features = json.loads(contenuto).get("features", [])
        if attesi is None:
            attesi = json.loads(contenuto).get("numberMatched")
            log.info("[%s] il servizio dichiara %s record", sigla, attesi)

        destinazione = percorso_libero(cartella, f"{nome_breve}_{start:05d}.json", ora_esecuzione)
        destinazione.write_bytes(contenuto)          # file grezzo, senza modifiche
        file_scritti += 1
        report.aggiungi(sha256=hashlib.sha256(contenuto).hexdigest(), url=url,
                        data_ora_download=data_ora, file=destinazione.name, layer=layer,
                        start_index=start, record=len(features), byte=len(contenuto),
                        http_status=r.status_code)
        gid_visti.update(f["properties"]["gid"] for f in features)
        log.info("[%s] startIndex=%d: %d record -> %s", sigla, start, len(features), destinazione.name)

        start += len(features)
        if len(features) < conteggio or (max_records and start >= max_records):
            break
        time.sleep(cfg["pausa"])

    attesi_effettivi = min(attesi, max_records) if (max_records and attesi is not None) else attesi
    return {"layer": layer, "file": file_scritti, "scaricati": len(gid_visti),
            "attesi": attesi_effettivi, "ok": attesi_effettivi == len(gid_visti)}
