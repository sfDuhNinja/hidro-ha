# Hidroelectrica pentru Home Assistant

Integrare neoficială pentru contul [iHidro](https://ihidro.ro) (Hidroelectrica România):
sold, scadență, indexul contorului, consum, trimiterea autocitirii și, pentru
**prosumatori**, energia produsă și compensațiile ANRE.

> Proiect independent, fără legătură cu Hidroelectrica. Folosește API-ul aplicației
> mobile, care se poate schimba fără notificare.

## Instalare (HACS)

1. HACS → ⋮ → **Depozite personalizate** → `https://github.com/sfDuhNinja/hidro-ha`, tip **Integrare**.
2. Instalează „Hidroelectrica" și repornește Home Assistant.
3. **Setări → Dispozitive și servicii → Adaugă integrare → Hidroelectrica** și introdu
   utilizatorul și parola de la iHidro.

Parola rămâne în Home Assistant; conexiunea la `ihidro.ro` verifică certificatul TLS.
Se folosește primul contract din cont.

## Entități

Datele se reîmprospătează la 6 ore.

| Entitate | Ce arată |
|---|---|
| Sold de plată | Valoarea facturii curente (RON) |
| Scadență | Data scadenței facturii |
| Index contor | Ultimul index consumat înregistrat oficial (kWh) |
| Index declarat | Indexul trimis de tine pentru perioada curentă |
| Ultima citire / Tip ultima citire | Data și tipul (autocitire, distribuitor, regularizare) |
| Consum ultima perioadă | Diferența dintre ultimele două citiri (kWh) |
| Fereastră autocitire | `on` cât timp se poate trimite indexul |
| Trimite indexul | Buton, vezi mai jos |
| Ultima trimitere | Rezultatul ultimei trimiteri |

Contoarele care nu sunt inteligente nu au curbă de consum: singura măsură e diferența
dintre citiri.

### Prosumator

Detectat automat, când contorul are citiri pe registrul de energie injectată (`1.8.0_P`).
Pentru un cont nou, entitățile apar singure după prima citire.

| Entitate | Ce arată |
|---|---|
| Index energie produsă | Indexul de energie injectată (kWh) |
| Producție ultima perioadă | Diferența dintre ultimele două citiri de producție |
| Compensații ANRE primite | Suma compensațiilor, cu detaliu pe ani în atribute |

Consumul și producția sunt urmărite separat. Butonul de trimitere a indexului este
dezactivat pentru prosumatori, citirea făcând-o distribuitorul.

> Suportul de prosumator urmează structura datelor din integrarea
> [cnecrea/hidroelectrica](https://github.com/cnecrea/hidroelectrica) și nu a fost încă
> validat pe un cont real cu istoric. Dacă o valoare nu iese, deschide un
> [issue](https://github.com/sfDuhNinja/hidro-ha/issues).

## Trimiterea indexului

1. Creează un helper `input_number.index_hidroelectrica_de_trimis`.
2. Pune în el indexul citit de pe contor.
3. Apasă **Trimite indexul**. Butonul e disponibil doar în fereastra de autocitire.

Înainte de trimitere se verifică local: fereastra deschisă, număr întreg, nu mai mic decât
ultimul index și nu cu mai mult de 2000 kWh peste el. Nu există reîncercare automată;
rezultatul apare în *Ultima trimitere* și într-o notificare. Un index trimis devine bază
de facturare, deci verifică valoarea înainte să apeși.

## Limitări

- Fără serie de consum lunar pentru contoarele ne-inteligente.
- Istoricul de facturi nu este expus de API pentru toate conturile.
- Indexul curent nu poate fi citit cât fereastra de autocitire e închisă.

## Dezvoltare

```bash
python3 -m venv .venv && .venv/bin/pip install pytest pytest-asyncio
.venv/bin/python -m pytest
```

Detalii despre API: [docs/API.md](docs/API.md). Scriptul `tools/recon.py` interoghează
API-ul cu contul tău și salvează răspunsurile (sesiunea în `~/.config/hidro-recon/`,
parola nu se salvează); redactează datele personale înainte să le publici ca fixture-uri.

## Licență

[MIT](LICENSE).

## Mulțumiri

Cunoașterea API-ului vine din [cnecrea/hidroelectrica](https://github.com/cnecrea/hidroelectrica)
(MIT). Codul e scris de la zero, fără licență plătită și cu verificarea TLS activă.
