# Harvester SITAP – Vincoli paesaggistici L.1497/39

## Cos'è un harvester

"Harvesting" vuol dire "raccolta". Un harvester è un programma che va a prendere i dati da un servizio
esterno (qui le API di SITAP) e li salva in locale, sempre nello stesso modo, ogni volta che lo lanci.

Le regole seguite sono tre:

1. **Si salva il dato grezzo.** Ogni risposta del server viene scritta su disco esattamente com'è arrivata,
   senza modifiche. Così si può sempre rifare l'elaborazione (per esempio il caricamento in PostGIS)
   partendo dall'originale.
2. **Si tiene traccia di tutto.** Per ogni file scaricato una riga in `report.csv` dice da quale URL viene,
   quando è stato scaricato e qual è la sua "impronta" (hash SHA-256).
3. **Non si cancella niente.** Ogni giorno ha la sua cartella, e se lanci l'harvester due volte nello stesso
   giorno i file nuovi non sovrascrivono quelli vecchi.

## Da dove prende i dati

Dal servizio WFS pubblico di SITAP (Ministero della Cultura), tre layer:

| Sigla | Layer | Contenuto | Record (6/11/2026) |
|---|---|---|---|
| `pun` | `sitap_wfs_ws:wms_ext_sitap_v1497_pun` | vincoli puntuali | 1.718 |
| `lin` | `sitap_wfs_ws:wms_ext_sitap_v1497_lin` | vincoli lineari | 185 |
| `pol` | `sitap_wfs_ws:wms_ext_sitap_v1497_pol` | vincoli poligonali | 8.313 |

Il server non restituisce tutto in una volta: dà **pagine da 500 record**. La chiamata è questa
(per i poligoni, prima pagina):

```
https://sitap.cultura.gov.it/geoserver/wfs?service=WFS&version=2.0.0&request=GetFeature
  &typeNames=sitap_wfs_ws:wms_ext_sitap_v1497_pol
  &outputFormat=application/json   -> risposta in GeoJSON
  &srsName=EPSG:4326               -> coordinate in gradi (lon/lat)
  &sortBy=gid                      -> ordine fisso (senza, il server dà errore 400)
  &count=500                       -> quanti record per pagina
  &startIndex=0                    -> da quale record partire: 0, 500, 1000, ...
```

## Cosa fa lo script, passo per passo

1. Crea la cartella `sitap/AAAA-MM-GG/` (la data di oggi).
2. Per ogni layer chiama la pagina con `startIndex=0`. Nella risposta legge `numberMatched`,
   cioè quanti record ci sono in totale.
3. Salva la risposta in un file, per esempio `wms_ext_sitap_v1497_pol_00000.json`
   (il numero finale è lo `startIndex`).
4. Calcola l'hash SHA-256 del file e scrive una riga in `report.csv`.
5. Passa alla pagina successiva (`startIndex` + 500), aspettando mezzo secondo per non
   sovraccaricare il server. Si ferma quando una pagina ha meno di 500 record: è l'ultima.
6. Se una richiesta fallisce, riprova fino a 4 volte, aspettando sempre di più (2, 4, 8 secondi).
7. Alla fine confronta i record scaricati (contando gli ID `gid` unici) con `numberMatched`
   e scrive nel log `OK` oppure `ATTENZIONE`.

## Cosa trovi dopo l'esecuzione

```
sitap/
  2026-11-06/
    report.csv                              <- una riga per ogni file scaricato
    harvest.log                             <- il diario dell'esecuzione
    wms_ext_sitap_v1497_pun_00000.json      <- dati grezzi, una pagina per file
    wms_ext_sitap_v1497_pun_00500.json
    ...
    wms_ext_sitap_v1497_pol_08000.json
```

In tutto sono 22 file JSON, circa 390 MB, scaricati in circa 2 minuti.

### report.csv

Separatore `;`, una riga per file:

| Colonna | Significato |
|---|---|
| `sha256` | impronta del contenuto del file: se cambia anche un solo carattere, cambia l'hash |
| `url` | l'URL esatto chiamato |
| `data_ora_download` | data e ora del download, con fuso orario (es. `2026-11-06T11:22:24+01:00`) |
| `file` | nome del file salvato |
| `layer` | layer SITAP |
| `start_index` | pagina (record di partenza) |
| `record` | quanti record ci sono nel file |
| `byte` | dimensione del file |
| `http_status` | risposta del server (200 = ok) |

**A cosa serve l'hash:** se domani scarichi di nuovo e l'hash di una pagina è identico, i dati di quella
pagina non sono cambiati. Se è diverso, qualcosa è cambiato. Puoi anche verificare che un file non sia
stato alterato ricalcolando l'hash.

### Più esecuzioni nello stesso giorno

- `report.csv` non viene riscritto: le nuove righe si aggiungono in fondo.
- I file già presenti restano. I nuovi prendono l'ora dell'esecuzione nel nome, per esempio
  `wms_ext_sitap_v1497_pun_00000_112444.json` (ore 11:24:44).

Un giorno diverso ha una cartella nuova.

## Come si usa (Windows)

Serve Python 3.10 o successivo. Dalla cartella del progetto:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python harvester.py
```

Opzioni:

```
python harvester.py --output D:\dati_harvest   # cartella radice diversa (default: quella corrente)
python harvester.py --layers pun lin           # solo alcuni layer (pun, lin, pol)
```

Lo script termina con codice `0` se è tutto OK e `1` se ci sono errori. Questo serve se in futuro
lo farai partire in automatico (per esempio con l'Utilità di pianificazione di Windows).

## Test fatto il 6/11/2026

- Tutti e tre i layer: 22 file, 1.718 + 185 + 8.313 record, conteggi uguali a `numberMatched`.
- Hash ricalcolati sui file: tutti corrispondono al report.
- ID (`gid`) uguali a quelli del CSV `vincoli_in_rete_dati_filtri.csv` estratto in precedenza.
- Seconda esecuzione lo stesso giorno: nessun file sovrascritto, report passato da 22 a 27 righe.

## Struttura del progetto

```
sitap_harvester/
  harvester.py       <- lo script
  requirements.txt   <- librerie necessarie (solo "requests")
  README.md          <- questo file
  .gitignore         <- esclude i dati scaricati dal versionamento
```

Il prossimo passo è il caricamento in PostgreSQL/PostGIS. Sarà un passaggio separato, che legge i file
JSON già salvati, così l'harvesting e il caricamento restano indipendenti.
