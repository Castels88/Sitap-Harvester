# Harvester SITAP

Scarica i vincoli paesaggistici L.1497/39 (artt. 136 e 157 del Codice dei beni culturali) dal servizio WFS pubblico di SITAP e li salva come file grezzi, con un report che traccia ogni file scaricato.

```
downloader (SITAP WFS) ──► file JSON grezzi ──► sitap/AAAA-MM-GG/
                       └─► report.csv (sha256, url, data e ora di ogni file)
```

La fonte è un servizio pubblico del Ministero della Cultura, interrogato in sola lettura e senza credenziali.

## Fonti

| Fonte | Contenuto | Servizio | Record (6/11/2026) |
|---|---|---|---|
| SITAP – Sistema Informativo Territoriale Ambientale Paesaggistico (MiC – DG ABAP) | Vincoli paesaggistici L.1497/39: punti, linee, poligoni | WFS 2.0 `https://sitap.cultura.gov.it/geoserver/wfs` | 1.718 + 185 + 8.313 |

Sono gli stessi layer mostrati da [Vincoli in Rete](https://vincoliinrete.beniculturali.it/vir/vir/vir.html) nel gruppo "Vincoli paesaggistici L.1497/39 (SITAP)": Vincoli in Rete li prende da SITAP, quindi si interroga direttamente la fonte.

**SITAP** (`sitap.py`): legge i layer `sitap_wfs_ws:wms_ext_sitap_v1497_pun`, `_lin` e `_pol` (sigle `pun`, `lin`, `pol`) con GetFeature paginate in GeoJSON, coordinate in WGS84 (`srsName=EPSG:4326`). Le pagine sono ordinate con `sortBy=gid`, che il servizio richiede per la paginazione: senza, risponde con errore 400. Ogni risposta viene salvata così com'è arrivata, senza modifiche.

## Formato dei dati

Ogni esecuzione scrive in `<OUTPUT_DIR>/sitap/AAAA-MM-GG/`:

| File | Contenuto |
|---|---|
| `wms_ext_sitap_v1497_<layer>_<startIndex>.json` | una pagina WFS grezza (GeoJSON `FeatureCollection`), es. `..._pol_01500.json` |
| `report.csv` | una riga per ogni file scaricato |
| `harvest.log` | log dell'esecuzione |

Campi dei record SITAP (in `properties`):

| Campo | Descrizione |
|---|---|
| `gid` | identificativo del record nel layer (univoco, usato per l'ordinamento) |
| `id`, `codvr` | codice del vincolo SITAP |
| `oggvin` | oggetto del vincolo (descrizione) |
| `ddecr` | data del decreto |
| `tpub`, `npub`, `dpub` | pubblicazione: tipo (es. GU), numero, data |
| `ente`, `leg` | ente che ha emanato il vincolo e norma |
| `flag_lettera_m` | indicatore SITAP |

Colonne di `report.csv` (separatore `;`):

| Colonna | Descrizione |
|---|---|
| `sha256` | hash SHA-256 del contenuto del file |
| `url` | URL della richiesta WFS |
| `data_ora_download` | data e ora del download, con fuso orario |
| `file`, `layer`, `start_index` | file salvato, layer e pagina |
| `record`, `byte`, `http_status` | numero di record, dimensione, risposta HTTP |

⚠️ Il servizio cambia a ogni risposta il `timeStamp` e l'`id` tecnico di ogni record (`fid-...`): lo `sha256` di una pagina è quindi diverso a ogni download anche se i vincoli non sono cambiati.

## Come si usa

Requisiti: Python 3.10 o successivo, accesso a `sitap.cultura.gov.it`, circa 400 MB di spazio libero per ogni esecuzione completa.

### Configurazione

Copiare `.env.example` come `.env` nella radice del progetto (facoltativo: senza `.env` valgono i default). Le stesse variabili si possono passare anche dall'ambiente.

| Variabile | Default | Significato |
|---|---|---|
| `OUTPUT_DIR` | `.` | Cartella radice: i file vanno in `<OUTPUT_DIR>/sitap/AAAA-MM-GG/` |
| `LAYERS` | `pun,lin,pol` | Layer da scaricare |
| `PAGE_SIZE` | `500` | Record per pagina WFS |
| `MAX_RECORDS` | `0` = tutti | Record massimi per layer, per le prove |
| `HTTP_RETRIES`, `HTTP_TIMEOUT` | `5`, `180` | Tentativi e timeout (secondi) delle richieste |
| `PAUSE_SECONDS` | `0.5` | Attesa tra una pagina e l'altra |
| `LOG_LEVEL` | `INFO` | Livello dei log |

⚠️ Un `MAX_RECORDS` basso (es. 20) serve solo per le prove: per scaricare tutto usare 0.

### Avvio

```
cd services/downloader
pip install -r requirements.txt
python main.py                               # tutti i layer
```

Esempi (Windows: `set VARIABILE=valore` prima del comando; Linux/macOS: `VARIABILE=valore python main.py`):

```
MAX_RECORDS=20 python main.py                # prova veloce
LAYERS=pol python main.py                    # un solo layer
OUTPUT_DIR=D:\harvest python main.py         # cartella radice diversa
```

Un download completo richiede circa 2 minuti e produce 22 file, circa 400 MB.

## Cosa succede durante un download

Per ogni layer il downloader chiede la prima pagina (`startIndex=0`) e legge `numberMatched`, cioè quanti record ci sono in totale. Poi scarica una pagina alla volta, aumentando `startIndex` di `PAGE_SIZE`, e si ferma quando una pagina ha meno record di quelli richiesti. Tra una pagina e l'altra aspetta `PAUSE_SECONDS`.

Ogni pagina viene salvata subito su disco e registrata in `report.csv`. Alla fine il downloader conta i `gid` unici scaricati e li confronta con `numberMatched`: nel log scrive `OK` oppure `ATTENZIONE: NON CORRISPONDE`.

Le richieste HTTP sono ritentate fino a `HTTP_RETRIES` volte, con attese crescenti (2, 4, 8 s…). Se un layer fallisce, gli altri vengono scaricati comunque; se almeno un layer fallisce o non corrisponde, il downloader esce con codice 1.

**Nessun file viene sovrascritto.** Ogni giorno ha la sua cartella. Se il downloader viene lanciato più volte nello stesso giorno, `report.csv` non viene riscritto ma le nuove righe si aggiungono in fondo, e i nuovi file prendono l'ora dell'esecuzione nel nome (es. `wms_ext_sitap_v1497_pun_00000_112444.json`).

## Struttura del progetto

```
services/
  downloader/       main.py (orchestrazione), sitap.py (fonte SITAP), common.py (configurazione, HTTP, report), requirements.txt
.env.example        impostazioni, da copiare come .env
```
