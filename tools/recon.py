#!/usr/bin/env python3
"""Faza 0 — recon pe API-ul Hidroelectrica (iHidro).

Se autentifică pe contul tău, apelează endpoint-urile de date și salvează răspunsurile
JSON *redactate* în tests/fixtures/, ca să știm ce câmpuri există înainte de a scrie
senzorii.

    python3 tools/recon.py          # refolosește sesiunea salvată
    python3 tools/recon.py --login  # forțează autentificare nouă

Parola se cere interactiv, nu se afișează și nu se scrie pe disc. Se salvează doar
tokenul de sesiune, în ~/.config/hidro-recon/session.json (permisiuni 600).

Spre deosebire de integrarea upstream (cnecrea/hidroelectrica), aici verificarea TLS
rămâne ACTIVĂ: certificatul ihidro.ro e valid (Sectigo OV, verificat 2026-08-19), deci
nu există motiv să trimitem parola pe o conexiune neverificată.

Fără dependențe externe — doar biblioteca standard.
"""

from __future__ import annotations

import base64
import getpass
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

API_BASE = "https://ihidro.ro"
LANG = "RO"
TIMEOUT = 30

PRE_AUTH_HEADERS = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}
POST_AUTH_HEADERS = {**PRE_AUTH_HEADERS, "SourceType": "1"}

EP = {
    "get_id": "/API/UserLogin/GetId",
    "validate": "/API/UserLogin/ValidateUserLogin",
    "user_setting": "/API/UserLogin/GetUserSetting",
    "master_data": "/API/UserLogin/GetMasterDataStatus",
    "multi_meter": "/Service/Usage/GetMultiMeter",
    "usage": "/Service/Usage/GetUsageGeneration",
    "window_dates": "/Service/SelfMeterReading/GetWindowDates",
    "pods": "/Service/SelfMeterReading/GetPods",
    "meter_value": "/Service/SelfMeterReading/GetMeterValue",
    "previous_read": "/Service/SelfMeterReading/GetPreviousMeterRead",
    "bill": "/Service/Billing/GetBill",
    "billing_history": "/Service/Billing/GetBillingHistoryList",
    "counter_series": "/Service/IndexHistory/GetMeterCounterSeries",
    "read_history": "/Service/IndexHistory/GetMeterReadHistory",
}

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
SESSION_FILE = Path.home() / ".config" / "hidro-recon" / "session.json"

# ── Redactare ──
PII_KEYS = {
    "address", "adresa", "street", "city", "locality", "postalcode", "zipcode",
    "firstname", "lastname", "name", "fullname", "customername", "username",
    "email", "emailid", "phone", "phonenumber", "mobile", "mobileno",
    "cnp", "iban", "bankaccount",
    # GetPreviousMeterRead expune numele clientului la distribuitor:
    "distcustomer", "distcustomerid", "distcontract",
}
ID_KEYS = {
    "utilityaccountnumber", "accountnumber", "userid", "pod", "podvalue",
    "equipmentno", "installationnumber", "serialnumber", "meternumber",
    "contractaccountid", "sessiontoken", "tokenid", "key",
    # GetPods folosește alte nume pentru aceiași identificatori:
    "installation", "accountid", "customernumber", "bpnumber", "invoicenumber",
}
_ids: dict[str, str] = {}


def _pseudo(v: Any) -> str:
    k = str(v)
    if k not in _ids:
        _ids[k] = f"ID_{len(_ids) + 1:02d}"
    return _ids[k]


def redact(o: Any) -> Any:
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            lk = k.lower().replace("_", "")
            if lk in PII_KEYS and v not in (None, "", [], {}):
                out[k] = "«redactat»"
            elif lk in ID_KEYS and v not in (None, "", [], {}):
                out[k] = _pseudo(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(o, list):
        return [redact(i) for i in o]
    return o


# ── HTTP ──

def post(endpoint: str, payload: dict, headers: dict) -> tuple[int, Any]:
    req = urllib.request.Request(
        f"{API_BASE}{endpoint}",
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        # Verificarea TLS rămâne activă (context implicit).
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, (json.loads(body) if body.strip() else None)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return e.code, {"_raw": body[:400]}
    except urllib.error.URLError as e:
        print(f"  ✗ rețea: {e.reason}")
        return 0, None


def basic(user: str, secret: str) -> str:
    return base64.b64encode(f"{user}:{secret}".encode()).decode()


def payload_of(resp: Any) -> Any:
    """Conținutul util: răspunsurile vin împachetate ca {result: {Data: ...}}.

    `Data` e uneori dict, alteori listă — nu presupune nimic despre formă.
    """
    if not isinstance(resp, dict):
        return None
    result = resp.get("result")
    if not isinstance(result, dict):
        return None
    return result.get("Data")


def data_of(resp: Any) -> dict:
    """Ca payload_of, dar garantează un dict (gol dacă `Data` e altceva)."""
    data = payload_of(resp)
    return data if isinstance(data, dict) else {}


# ── Sesiune ──

def save_session(user_id: str, token: str) -> None:
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_FILE.touch(mode=0o600, exist_ok=True)
    SESSION_FILE.chmod(0o600)
    SESSION_FILE.write_text(json.dumps({"user_id": user_id, "session_token": token}))


def load_session() -> tuple[str, str] | None:
    if not SESSION_FILE.exists():
        return None
    try:
        d = json.loads(SESSION_FILE.read_text())
        if d.get("user_id") and d.get("session_token"):
            return d["user_id"], d["session_token"]
    except (json.JSONDecodeError, OSError):
        pass
    return None


def auth_headers(user_id: str, token: str) -> dict:
    return {**POST_AUTH_HEADERS, "Authorization": f"Basic {basic(user_id, token)}"}


_creds: dict[str, str] = {}  # doar în memorie, pe durata rulării


def login(prompt: bool = True) -> tuple[str, str]:
    """GetId → ValidateUserLogin. Întoarce (user_id, session_token)."""
    status, resp = post(EP["get_id"], {}, dict(PRE_AUTH_HEADERS))
    d = data_of(resp)
    key, token_id = d.get("key"), d.get("tokenId")
    if not key or not token_id:
        sys.exit(f"✗ GetId a eșuat (HTTP {status}): {json.dumps(resp)[:300]}")

    if prompt or not _creds:
        _creds["u"] = input("Utilizator iHidro: ").strip()
        _creds["p"] = getpass.getpass("Parolă (nu se afișează, nu se salvează): ")
    username, password = _creds["u"], _creds["p"]
    now = datetime.now().strftime("%m/%d/%Y %H:%M:%S")

    status, resp = post(EP["validate"], {
        "deviceType": "MobileApp", "OperatingSystem": "Android",
        "UpdatedDate": now, "Deviceid": "", "SessionCode": "",
        "LanguageCode": LANG, "password": password, "UserId": username,
        "TFADeviceid": "", "OSVersion": 14, "TimeOffSet": "120",
        "LUpdHideShow": now, "Browser": "NA",
    }, {**PRE_AUTH_HEADERS, "Authorization": f"Basic {basic(key, token_id)}"})

    table = data_of(resp).get("Table") or []
    if not table:
        sys.exit(f"✗ Autentificare eșuată (HTTP {status}) — credențiale invalide?")
    row = table[0]
    user_id, session_token = row.get("UserID", ""), row.get("SessionToken", "")
    if not user_id or not session_token:
        sys.exit("✗ Autentificare eșuată — UserID sau SessionToken lipsă.")
    print("✓ Autentificat.")
    return user_id, session_token


def resume() -> tuple[str, str] | None:
    saved = load_session()
    if not saved:
        print("→ Nicio sesiune salvată. Autentificare o singură dată; dacă duci\n"
              "  rularea până la capăt, următoarele nu vor mai cere nimic.\n")
        return None
    user_id, token = saved
    status, resp = post(EP["user_setting"], {"UserID": user_id},
                        auth_headers(user_id, token))
    if status == 200 and data_of(resp):
        print("✓ Sesiune reluată din cache (fără parolă).")
        return saved
    print(f"→ Sesiunea salvată nu mai e valabilă (HTTP {status}). Autentificare nouă.")
    return None


# ── Colectare ──

_session: dict[str, str] = {}


def call(endpoint: str, payload: dict) -> tuple[int, Any]:
    """POST autentificat, cu o singură re-autentificare la 401.

    Sesiunea Hidroelectrica expiră selectiv: unele endpoint-uri răspund 401 pe un
    token care tocmai a funcționat în altă parte. Upstream face același lucru.
    """
    status, data = post(endpoint, payload, auth_headers(_session["u"], _session["t"]))
    if status != 401:
        return status, data
    if not _creds:
        print("    (401 — e nevoie de re-autentificare)")
        return status, data
    print("    (401 — re-autentificare și reîncercare)")
    user_id, token = login(prompt=False)
    _session.update(u=user_id, t=token)
    save_session(user_id, token)
    return post(endpoint, payload, auth_headers(user_id, token))

def _shape(data: Any) -> str:
    """Descriere scurtă a formei, indiferent de tip."""
    if isinstance(data, dict):
        return f"dict, chei: {sorted(map(str, data))[:8]}"
    if isinstance(data, list):
        if data and isinstance(data[0], dict):
            return f"listă[{len(data)}], chei element: {sorted(map(str, data[0]))[:6]}"
        return f"listă[{len(data)}]"
    if data is None:
        return "Data lipsă"
    return type(data).__name__


def dump(name: str, status: int, payload: Any) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / f"{name}.json").write_text(json.dumps(
        {"_http_status": status, "data": redact(payload)}, indent=2, ensure_ascii=False))
    if status == 200 and payload is not None:
        print(f"  ✓ {name:24s} {_shape(payload_of(payload))}")
    else:
        print(f"  ✗ {name:24s} HTTP {status}")


def main() -> None:
    print("Recon Hidroelectrica — Faza 0\n" + "─" * 46)

    session = None if "--login" in sys.argv else resume()
    if session is None:
        session = login()
        save_session(*session)
        print(f"  (sesiune salvată în {SESSION_FILE})")
    user_id, token = session
    _session.update(u=user_id, t=token)

    print("\n[1] Cont și contracte")
    status, user_setting = call(EP["user_setting"], {"UserID": user_id})
    dump("user_setting", status, user_setting)
    st, d = call(EP["master_data"], {"UserID": user_id})
    dump("master_data_status", st, d)

    data = data_of(user_setting)
    accounts = []
    for tk in ("Table1", "Table2"):
        for e in data.get(tk) or []:
            uan = (e.get("UtilityAccountNumber") or "").strip()
            if uan and uan not in [a[0] for a in accounts]:
                accounts.append((uan, e.get("AccountNumber", ""), e.get("Pod", "")))
    if not accounts:
        sys.exit("✗ Niciun cont găsit. Verifică tests/fixtures/user_setting.json")
    uan, acc, pod = accounts[0]
    bp = ""
    for tk in ("Table1", "Table2"):
        for e in data.get(tk) or []:
            if not bp and e.get("BpNumber"):
                bp = str(e["BpNumber"])
    print(f"  → {len(accounts)} cont(uri); folosesc primul."
          f"{' BpNumber găsit.' if bp else ' ATENȚIE: BpNumber lipsă.'}")

    base = {"MeterType": "E", "UserID": user_id,
            "UtilityAccountNumber": uan, "AccountNumber": acc}
    usage_payload = {
        "date": "", "IsCSR": False, "IsUSD": False, "Mode": "M", "HourlyType": "H",
        "UsageType": "e", "UsageOrGeneration": False, "GroupId": 0,
        "LanguageCode": LANG, "Type": "D", "MeterNumber": "",
        "IsEnterpriseUser": False, "SeasonType": 0, "DateFromDaily": "",
        "IsNetUsage": False, "TimeOffset": "120", "UserType": "Residential",
        "DateToDaily": "", "UtilityId": 0, "IsLastTendays": False,
        "UserID": user_id, "UtilityAccountNumber": uan, "AccountNumber": acc,
    }

    print("\n[2] Facturi")
    st, d = call(EP["bill"], {"LanguageCode": LANG, "UserID": user_id, "IsBillPDF": "0",
                              "UtilityAccountNumber": uan, "AccountNumber": acc})
    dump("bill", st, d)
    st, d = call(EP["billing_history"], {"LanguageCode": LANG, "UserID": user_id,
                                         "UtilityAccountNumber": uan,
                                         "AccountNumber": acc,
                                         "FromDate": "", "ToDate": ""})
    dump("billing_history", st, d)

    print("\n[3] Contor, consum, autocitire")
    raw: dict[str, Any] = {}
    for name, ep, pl in [
        ("multi_meter", EP["multi_meter"], base),
        ("window_dates", EP["window_dates"], base),
        ("pods", EP["pods"], base),
        ("usage", EP["usage"], usage_payload),
    ]:
        st, d = call(ep, pl)
        raw[name] = d
        dump(name, st, d)

    meter_no = ""

    def find_meter(o: Any) -> None:
        nonlocal meter_no
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() == "meternumber" and v and not meter_no:
                    meter_no = str(v)
                else:
                    find_meter(v)
        elif isinstance(o, list):
            for i in o:
                find_meter(i)

    find_meter(raw.get("multi_meter"))

    print("\n[4] Istoric citiri (miza rundei)")
    # Necesită InstallationNumber și podValue din GetPods. Se citesc din răspunsul
    # BRUT din memorie — în fixture sunt pseudonimizate, deci inutilizabile.
    pods_raw = raw.get("pods")
    inst = pod_value = ""

    def find(o: Any) -> None:
        nonlocal inst, pod_value
        if isinstance(o, dict):
            for k, v in o.items():
                lk = k.lower()
                if lk in ("installationnumber", "installation") and v and not inst:
                    inst = str(v)
                elif lk in ("podvalue", "pod") and v and not pod_value:
                    pod_value = str(v)
                else:
                    find(v)
        elif isinstance(o, list):
            for i in o:
                find(i)

    find(pods_raw)
    if not inst:
        print("  ! InstallationNumber negăsit în pods.json (posibil redactat) —")
        print("    istoricul de citiri nu poate fi cerut automat. Vezi fixture-ul.")
    else:
        st, d = call(EP["read_history"], {
            "utilityAccountNumber": uan, "podValue": pod_value or pod,
            "LanguageCode": LANG, "InstallationNumber": inst, "SerialNumber": []})
        dump("meter_read_history", st, d)
        st, d = call(EP["counter_series"], {
            "utilityAccountNumber": uan, "podValue": pod_value or pod,
            "LanguageCode": LANG, "InstallationNumber": inst})
        dump("meter_counter_series", st, d)

        # Payload propriu, din upstream (y0.java). Apelul anterior folosea din
        # greșeală payload-ul generic — de aici cele două HTTP 400, NU fereastra
        # închisă, cum presupusesem.
        st, d = call(EP["previous_read"], {
            "UtilityAccountNumber": uan,
            "InstallationNumber": inst,
            "podValue": pod_value or pod,
            "LanguageCode": LANG,
            "UserID": user_id,
            "BasicValue": "",
            "CustomerNumber": bp,
            "Distributor": "",
        })
        dump("previous_meter_read", st, d)
        raw["previous_meter_read"] = d

    print("\n[5] Variante pentru consum (usage a răspuns gol)")
    # Prima variantă a întors toate câmpurile null deși Status=1. Încercăm alte
    # combinații de Mode/Type și un interval explicit, ca să vedem care umple datele.
    from datetime import timedelta
    azi = datetime.now()
    anul_trecut = (azi - timedelta(days=365)).strftime("%m/%d/%Y")
    for eticheta, extra in [
        ("usage_mode_d", {"Mode": "D", "Type": "M"}),
        ("usage_cu_interval", {"Mode": "M", "Type": "D",
                               "DateFromDaily": anul_trecut,
                               "DateToDaily": azi.strftime("%m/%d/%Y"),
                               "date": azi.strftime("%m/%d/%Y")}),
        ("usage_meter", {"Mode": "M", "Type": "D", "MeterNumber": meter_no}),
    ]:
        pl = {**usage_payload, **extra}
        st, d = call(EP["usage"], pl)
        dump(eticheta, st, d)

    print("\n[6] GetMeterValue — DOAR citire/validare, nu trimite nimic")
    # Construim entitatea exact ca butonul, ca să vedem răspunsul complet.
    # SubmitSelfMeterRead NU e apelat nicăieri în acest script.
    prev = raw.get("previous_meter_read")
    pdata = (prev or {}).get("result", {}).get("Data") if isinstance(prev, dict) else None
    records = [r for r in pdata if isinstance(r, dict)] if isinstance(pdata, list) else []
    if not records:
        print("  ! Nu am înregistrarea anterioară — sar peste.")
    else:
        keys = ("contractAccountID", "accountID", "equipmentNo", "registerNo",
                "registerType", "uom", "preDecimals", "postDecimals", "noMROrder",
                "prevMRResult", "prevMRDate", "prevMRRsn", "prevMRCat", "serialNumber",
                "pod", "registerCat", "distributor", "meterInterval", "supplier",
                "distCustomer", "distCustomerId", "distContract", "distContractDate")
        try:
            test_val = int(float(records[0].get("prevMRResult") or 0)) + 1
        except (TypeError, ValueError):
            test_val = 1
        entities = []
        for rec in records:
            ent = {k: rec.get(k, "") for k in keys}
            ent["newmeterread"] = str(test_val)
            ent["NewMeterReadDate"] = datetime.now().strftime("%d/%m/%Y")
            entities.append(ent)
        print(f"  valoare de test: {test_val} (NU se trimite)")
        st, d = call(EP["meter_value"], {
            "UserId": user_id, "podValue": pod_value or pod,
            "InstallationNumber": inst, "AccountNumber": acc,
            "UsageSelfMeterReadEntity": entities,
        })
        dump("meter_value", st, d)
        if isinstance(d, dict):
            print(f"  → responsestatus={d.get('responsestatus')} status_code={d.get('status_code')}")
            res = d.get("result")
            if isinstance(res, dict):
                print(f"  → chei result: {sorted(res)}")
                print(f"  → Status={res.get('Status')!r} Message={res.get('Message')!r}")

    print("\n" + "─" * 46)
    print(f"Fixture-uri în {FIXTURES}")


if __name__ == "__main__":
    main()
