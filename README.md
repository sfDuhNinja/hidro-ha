# hidro-ha

Integrare Home Assistant pentru Hidroelectrica (iHidro) — vizibilitate pe costuri
pentru locuința din București (`ha-dizonaur`, HA „Dizonaur").

Suportă și conturile de **prosumator** (contor bidirecțional) — vezi secțiunea de mai jos.

## Stadiu

- [x] Faza 0 — recon rulat, fixture-uri capturate
- [x] Faza 1 — citire: 5 entități
- [x] Trimiterea indexului — buton + senzor de status, 66 de teste trec
- [x] Instalat pe `ha-dizonaur`

## Faza 0

```
python3 tools/recon.py          # refolosește sesiunea salvată
python3 tools/recon.py --login  # forțează autentificare nouă
```

Parola se cere interactiv, nu se afișează și nu ajunge pe disc. Se salvează doar tokenul
de sesiune, în `~/.config/hidro-recon/session.json` (permisiuni 600), în afara proiectului.

## Diferențe față de integrarea upstream

[cnecrea/hidroelectrica](https://github.com/cnecrea/hidroelectrica) e MIT, dar are gate
de licență plătită. Cunoașterea API-ului e preluată de acolo (permis de MIT); codul e scris
de la zero, fără gate.

**Verificarea TLS rămâne activă.** Upstream dezactivează validarea certificatului
(`CERT_NONE`) cu motivul „certificat problematic". Verificat pe 2026-08-19: certificatul
`ihidro.ro` e valid (Sectigo OV, expiră 16.03.2027) și trece validarea normală. Cum prin
conexiune trece parola contului, nu există motiv să renunțăm la verificare.

## API

Backend SmartCMobile, proxy `https://ihidro.ro`, headere `SourceType: 0` (pre-auth) și
`1` (post-auth).

Autentificare în doi pași, **fără MFA**:
1. `POST /API/UserLogin/GetId` → `key`, `tokenId`
2. `POST /API/UserLogin/ValidateUserLogin` cu `Basic base64(key:tokenId)` → `UserID`, `SessionToken`

Apelurile de date folosesc `Basic base64(UserID:SessionToken)`.
Răspunsurile sunt împachetate ca `{result: {Data: {...}}}`.

| Zonă | Endpoint |
|---|---|
| Conturi | `UserLogin/GetUserSetting` |
| Factură curentă | `Billing/GetBill` |
| Istoric facturi | `Billing/GetBillingHistoryList` |
| Consum | `Usage/GetUsageGeneration` |
| Contor | `Usage/GetMultiMeter`, `SelfMeterReading/GetMeterValue` |
| Fereastră autocitire | `SelfMeterReading/GetWindowDates` |
| Istoric citiri | `IndexHistory/GetMeterReadHistory` |

## Entități (citire)

| Entitate | Sursă |
|---|---|
| `sensor.hidroelectrica_sold_de_plata` | `GetBill` |
| `sensor.hidroelectrica_scadenta` | `GetBill` (`timestamp`) |
| `sensor.hidroelectrica_index_contor` | `GetMeterReadHistory` |
| `sensor.hidroelectrica_consum_ultima_perioada` | delta ultimelor două citiri |
| `binary_sensor.hidroelectrica_fereastra_autocitire` | `GetWindowDates` |

## Prosumator

Detectat automat: contorul întoarce citiri pe registrul `1.8.0_P` (energie injectată).
Registrele nu se amestecă — `Index contor` și `Consum ultima perioadă` folosesc doar `1.8.0`.

| Entitate (doar la prosumator) | Sursă |
|---|---|
| `sensor.…_index_energie_produsa` | `GetMeterReadHistory`, registrul `1.8.0_P` |
| `sensor.…_productie_ultima_perioada` | delta ultimelor două citiri de producție |
| `sensor.…_compensatii_anre_primite` | `GetBillingHistoryList`, plățile cu canal `Comp ANRE…` |

Butonul de trimitere index e **indisponibil** pentru prosumator (citirea o face distribuitorul).

> Structura datelor de prosumator e construită după integrarea upstream, nu după o captură
> reală; fixture-urile `*_prosumer.json` sunt sintetice. Verifică valorile pe un cont real.

## Ce NU se poate

- **Serie de consum lunar.** Contorul nu e AMI (`IsAMI: false`, `UsageCycle: "NA"`);
  `GetUsageGeneration` întoarce `objUsageGenerationResultSetTwo: []` indiferent de
  parametri. Singura măsură de consum e delta dintre citiri.
- **Istoric de facturi.** `GetBillingHistoryList` răspunde 200, dar toate cele trei
  entități sunt `None` pentru acest cont.
- **Index curent în afara ferestrei.** `GetMeterValue` și `GetPreviousMeterRead`
  întorc HTTP 400 cât timp fereastra de autocitire e închisă.

## Trimiterea indexului

`input_number.index_hidroelectrica_de_trimis` (helper) + `button.…_trimite_indexul`.
Butonul e **indisponibil** în afara ferestrei de autocitire.

La apăsare, în ordine — fiecare pas poate opri fluxul:

1. verificări locale: fereastră deschisă, valoare întreagă, ≥ ultimul index din istoric,
   diferență sub `MAX_DELTA_KWH` (2000)
2. `GetPreviousMeterRead` proaspăt — structura contorului se poate schimba lunar
3. `GetMeterValue` — **test de fum, nu validare** (vezi mai jos); blochează doar
   la erori explicite
4. `SubmitSelfMeterRead`

Rezultatul ajunge în `sensor.…_ultima_trimitere` (un `button` din HA nu poate întoarce
nimic în interfață) plus o notificare persistentă. **Fără retry automat**: la eșec parțial
nu știm dacă serverul a înregistrat.

### `UsageSelfMeterReadEntity`

Nu e o structură nouă: e înregistrarea din `GetPreviousMeterRead` copiată **verbatim**,
cu aceleași nume de chei (`contractAccountID`, nu `UtilityAccountNumber`), plus
`newmeterread` și `NewMeterReadDate` (format `DD/MM/YYYY`). O cheie redenumită rupe apelul.

`GetPreviousMeterRead` cere payload propriu — `InstallationNumber`, `podValue`,
`CustomerNumber` (= `BpNumber`), `BasicValue`, `Distributor`. Cu payload-ul generic
răspunde HTTP 400, indiferent dacă fereastra e deschisă.

### `GetMeterValue` NU validează valoarea

Numele înșală. E un *getter*: caută o citire deja înregistrată pentru perioada
curentă. Răspunsul normal înainte de o autocitire (măsurat 22.08.2026):

```json
{"status_code": 200, "responsestatus": 0, "result": {"Message": "No Record Found"}}
```

Cu payload greșit serverul răspunde **400**; cu payload corect răspunde **200** chiar
și când nu găsește nimic. Deci un 200 confirmă că identificatorii sunt acceptați — util
ca test de fum, dar **valoarea indexului nu e verificată de nimeni înainte de trimitere**.
Validarea reală se întâmplă în `SubmitSelfMeterRead`.

Consecință: singurele verificări dinaintea trimiterii sunt cele **locale** —
fereastră deschisă, număr întreg, ≥ ultima citire din istoric, salt sub `MAX_DELTA_KWH`.

### Praguri de validare

`prevMRResult` din `GetPreviousMeterRead` e ultima citire **oficială a distribuitorului**
(16294, aprilie) și poate fi mai veche decât ultima autocitire din istoric (16564, iunie).
Pragul de jos se ia din istoric, nu din `prevMRResult`.

## Instalare (HACS)

1. HACS → ⋮ → *Custom repositories* → URL `https://github.com/sfDuhNinja/hidro-ha`, tip *Integration*.
2. Instalează „Hidroelectrica", repornește Home Assistant.
3. *Setări → Dispozitive și servicii → Adaugă integrare → Hidroelectrica*.
