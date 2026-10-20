"""Extragerea valorilor din răspunsurile API Hidroelectrica.

Funcții pure, fără dependențe de Home Assistant — testabile pe fixture-urile din
Faza 0. Toate întorc None/valori neutre în loc să arunce: un câmp lipsă trebuie să
lase un singur senzor `unknown`, nu să doboare integrarea.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def payload_of(resp: Any) -> Any:
    """Conținutul util. `Data` e uneori dict, alteori listă — nu presupune nimic."""
    if not isinstance(resp, dict):
        return None
    result = resp.get("result")
    if not isinstance(result, dict):
        return None
    return result.get("Data")


def result_of(resp: Any) -> dict:
    """Unele endpoint-uri (GetBill) pun datele direct în `result`, fără `Data`."""
    if not isinstance(resp, dict):
        return {}
    result = resp.get("result")
    return result if isinstance(result, dict) else {}


def parse_amount(value: Any) -> float | None:
    """Sumele vin ca text cu virgulă zecimală: '443,90'."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return float(value.strip().replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _as_float(value: Any) -> float | None:
    """Numeric tolerant, inclusiv pentru numere venite ca text."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return parse_amount(value)


def parse_date(value: Any) -> date | None:
    """Acceptă 'YYYYMMDD', 'DD/MM/YYYY' și ISO."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y%m%d", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# ── Factură ──

def bill_amount(resp: Any) -> float | None:
    return parse_amount(result_of(resp).get("billamount"))


def bill_due_date(resp: Any) -> date | None:
    return parse_date(result_of(resp).get("duedate"))


def bill_details(resp: Any) -> dict[str, Any]:
    result = result_of(resp)
    if not result:
        return {}
    return {
        "rest_de_plata": parse_amount(result.get("rembalance")),
        "data_scadenta": str(bill_due_date(resp) or ""),
    }


# ── Fereastra de autocitire ──

def _window(resp: Any) -> dict:
    data = payload_of(resp)
    return data if isinstance(data, dict) else {}


def window_open(resp: Any) -> bool:
    return str(_window(resp).get("Is_Window_Open", "0")).strip() == "1"


def window_details(resp: Any) -> dict[str, Any]:
    window = _window(resp)
    if not window:
        return {}
    return {
        "zi_deschidere": window.get("OpeningDate"),
        "zi_inchidere": window.get("ClosingDate"),
        "urmatoarea_deschidere": window.get("NextMonthOpeningDate"),
        "urmatoarea_inchidere": window.get("NextMonthClosingDate"),
    }


# ── Citiri de index ──

def _readings(resp: Any) -> list[dict]:
    """Citirile, cronologic. Registrul 1.8.0 = energie activă consumată."""
    data = payload_of(resp)
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        when = parse_date(item.get("Date"))
        index = item.get("Index")
        if when is None or not isinstance(index, (int, float)) or isinstance(index, bool):
            continue
        rows.append({**item, "_date": when, "_index": float(index)})
    return sorted(rows, key=lambda r: r["_date"])


def latest_index(resp: Any) -> float | None:
    rows = _readings(resp)
    return rows[-1]["_index"] if rows else None


def latest_index_details(resp: Any) -> dict[str, Any]:
    rows = _readings(resp)
    if not rows:
        return {}
    last = rows[-1]
    return {
        "data_citire": str(last["_date"]),
        "tip_citire": last.get("ReadingType"),
        "registru": last.get("Registers"),
        "descriere": last.get("RegisterDescription"),
        "numar_citiri": len(rows),
    }


def consumption_since_previous(resp: Any) -> float | None:
    """Consumul dintre ultimele două citiri, în kWh.

    Singura măsură de consum disponibilă: contorul nu e inteligent, deci
    Hidroelectrica nu expune curbă de consum pentru acest loc.
    """
    rows = _readings(resp)
    if len(rows) < 2:
        return None
    delta = rows[-1]["_index"] - rows[-2]["_index"]
    return round(delta, 3) if delta >= 0 else None


def consumption_details(resp: Any) -> dict[str, Any]:
    rows = _readings(resp)
    if len(rows) < 2:
        return {}
    previous, last = rows[-2], rows[-1]
    days = (last["_date"] - previous["_date"]).days
    delta = last["_index"] - previous["_index"]
    out: dict[str, Any] = {
        "de_la": str(previous["_date"]),
        "pana_la": str(last["_date"]),
        "zile": days,
        "index_anterior": previous["_index"],
        "index_curent": last["_index"],
    }
    if days > 0 and delta >= 0:
        out["medie_zilnica"] = round(delta / days, 2)
    return out


# ── Conturi ──

def accounts(resp: Any) -> list[dict[str, str]]:
    """Conturile din GetUserSetting (Table1 + Table2), fără duplicate."""
    data = payload_of(resp)
    if not isinstance(data, dict):
        return []
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for key in ("Table1", "Table2"):
        for entry in data.get(key) or []:
            if not isinstance(entry, dict):
                continue
            uan = str(entry.get("UtilityAccountNumber", "")).strip()
            if uan and uan not in seen:
                seen.add(uan)
                found.append({
                    "utility_account_number": uan,
                    "account_number": str(entry.get("AccountNumber", "")),
                    "pod": str(entry.get("Pod", "")),
                    # CustomerNumber pentru autocitire — API-ul îl cere sub alt nume.
                    "bp_number": str(entry.get("BpNumber", "")),
                })
    return found


def pod_installation(resp: Any) -> tuple[str, str]:
    """(pod, installation) din GetPods — cheile diferă de cele din GetUserSetting."""
    data = payload_of(resp)
    if not isinstance(data, list):
        return "", ""
    for item in data:
        if isinstance(item, dict):
            return str(item.get("pod", "")), str(item.get("installation", ""))
    return "", ""


# ── Autocitire ──
#
# `UsageSelfMeterReadEntity` NU e o structură nouă: e înregistrarea din
# GetPreviousMeterRead copiată verbatim, cu ACELEAȘI nume de chei, plus valoarea
# nouă. Redenumirea vreunei chei (ex. contractAccountID → UtilityAccountNumber)
# face apelul să eșueze.

_ENTITY_KEYS = (
    "contractAccountID", "accountID", "equipmentNo", "registerNo", "registerType",
    "uom", "preDecimals", "postDecimals", "noMROrder", "prevMRResult", "prevMRDate",
    "prevMRRsn", "prevMRCat", "serialNumber", "pod", "registerCat", "distributor",
    "meterInterval", "supplier", "distCustomer", "distCustomerId", "distContract",
    "distContractDate",
)


def previous_read_records(resp: Any) -> list[dict]:
    """Înregistrările citirii anterioare — una per registru de contor."""
    data = payload_of(resp)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        items = data.get("objPreviousMeterReadData")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


def previous_read_value(resp: Any) -> float | None:
    """`prevMRResult` din prima înregistrare.

    Atenție: e ultima citire *oficială* a distribuitorului, care poate fi mai
    veche decât ultima autocitire din istoric. Nu o folosi singură ca prag de
    validare — vezi `submission_blocker`.
    """
    for record in previous_read_records(resp):
        value = _as_float(record.get("prevMRResult"))
        if value is not None:
            return value
    return None


def build_usage_entities(resp: Any, new_value: int, read_date: str) -> list[dict]:
    """Entitățile de autocitire, una per registru."""
    entities = []
    for record in previous_read_records(resp):
        entity = {key: record.get(key, "") for key in _ENTITY_KEYS}
        entity["newmeterread"] = str(new_value)
        entity["NewMeterReadDate"] = read_date
        entities.append(entity)
    return entities


def submission_blocker(
    new_value: float | None,
    last_index: float | None,
    window_is_open: bool,
    max_delta: float,
) -> str | None:
    """Motivul pentru care trimiterea NU trebuie făcută, sau None dacă e în regulă.

    Verificări locale, înaintea oricărui apel de rețea. Pragul de jos e ultima
    citire cunoscută din istoric — nu `prevMRResult`, care poate fi mai veche.
    """
    if not window_is_open:
        return "Fereastra de autocitire este închisă."
    if new_value is None:
        return "Nu există o valoare de trimis."
    if new_value != int(new_value):
        return "Indexul trebuie să fie un număr întreg."
    if new_value <= 0:
        return "Indexul trebuie să fie mai mare decât zero."
    if last_index is not None:
        if new_value < last_index:
            return (
                f"Indexul introdus ({new_value:.0f}) e mai mic decât ultimul "
                f"transmis ({last_index:.0f}). Contorul nu merge înapoi."
            )
        if new_value > last_index + max_delta:
            return (
                f"Diferența față de ultimul index ({last_index:.0f}) e de "
                f"{new_value - last_index:.0f} kWh — implauzibil. Verifică cifrele."
            )
    return None


def api_message(resp: Any) -> str:
    """Mesajul întors de API, pentru raportare."""
    if not isinstance(resp, dict):
        return ""
    result = resp.get("result")
    if isinstance(result, dict):
        for key in ("Message", "message", "StatusMessage"):
            if result.get(key):
                return str(result[key])
    error = resp.get("error")
    if isinstance(error, dict):
        for key in ("Message", "StatusMessage"):
            if error.get(key):
                return str(error[key])
    return ""


def api_ok(resp: Any) -> bool:
    """True dacă răspunsul indică succes."""
    if not isinstance(resp, dict):
        return False
    if resp.get("responsestatus") == 1 and resp.get("status_code") == 200:
        result = resp.get("result")
        if isinstance(result, dict) and "Status" in result:
            return str(result.get("Status")) in ("1", "True", "true")
        return True
    return False


def latest_reading_date(resp: Any) -> date | None:
    """Data ultimei citiri de index."""
    rows = _readings(resp)
    return rows[-1]["_date"] if rows else None


def latest_reading_type(resp: Any) -> str | None:
    """Cine a făcut ultima citire: 'Autocitire', 'Regularizare', citire distribuitor…"""
    rows = _readings(resp)
    if not rows:
        return None
    tip = rows[-1].get("ReadingType")
    return str(tip) if tip else None


def reading_history(resp: Any) -> list[dict[str, Any]]:
    """Istoricul complet al citirilor, cronologic — pentru atribute."""
    return [
        {
            "data": str(r["_date"]),
            "index": r["_index"],
            "tip": r.get("ReadingType"),
            "registru": r.get("Registers"),
        }
        for r in _readings(resp)
    ]


def lookup_blocker(resp: Any) -> str | None:
    """Motivul pentru care apelul `GetMeterValue` indică o problemă, sau None.

    ATENȚIE la ce este și ce NU este acest endpoint. Numele sugerează validare,
    dar e un *getter*: caută o citire deja înregistrată pentru perioada curentă.
    Răspunsul normal înainte de o autocitire e HTTP 200 cu
    `{"responsestatus": 0, "result": {"Message": "No Record Found"}}` — adică
    „nu ai trimis încă nimic luna asta". Nu e o respingere a valorii.

    Verificat pe 2026-08-22: cu payload greșit serverul răspunde 400; cu payload
    corect răspunde 200 chiar și când nu găsește nimic. Deci un 200 confirmă că
    identificatorii sunt acceptați — un test de fum util, dar NU o validare a
    indexului. Valoarea e verificată abia de SubmitSelfMeterRead.
    """
    if not isinstance(resp, dict):
        return "Răspuns invalid de la Hidroelectrica."
    if isinstance(resp.get("error"), dict):
        mesaj = api_message(resp) or "eroare necomunicată"
        return f"Hidroelectrica a semnalat o eroare: {mesaj}"
    if resp.get("responsestatus") == -1:
        mesaj = api_message(resp) or "motiv necomunicat"
        return f"Cerere respinsă: {mesaj}"
    return None


def declared_index(resp: Any) -> float | None:
    """Indexul declarat pentru perioada curentă, din `GetMeterValue`.

    Sursa pe care o afișează și aplicația mobilă. Apare în câteva secunde după
    trimitere, spre deosebire de `GetMeterReadHistory`, care listează doar citirile
    procesate oficial și rămâne în urmă (măsurat: încă neactualizat la 5 minute).

    Semnătura răspunsului, verificată în ambele stări pe 2026-08-22:
      fără citire → responsestatus 0, result.Message = "No Record Found"
      cu citire   → responsestatus 1, result.data = "16984"
    """
    if not isinstance(resp, dict) or resp.get("responsestatus") != 1:
        return None
    result = resp.get("result")
    if not isinstance(result, dict):
        return None
    return _as_float(result.get("data"))
