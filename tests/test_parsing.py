"""Parsarea, verificată pe răspunsurile reale capturate în Faza 0."""

from datetime import date

import pytest


# ── Sume și date ──

@pytest.mark.parametrize("brut,asteptat", [
    ("443,90", 443.90),
    ("1.234,56", 1234.56),   # separator de mii
    ("0,00", 0.0),
    (12.5, 12.5),
    ("", None), (None, None), ("n/a", None), (True, None),
])
def test_parsarea_sumelor_cu_virgula(parsing, brut, asteptat):
    assert parsing.parse_amount(brut) == asteptat


@pytest.mark.parametrize("brut,asteptat", [
    ("20260921", date(2026, 9, 21)),      # GetBill
    ("22/06/2026", date(2026, 6, 22)),    # GetMeterReadHistory
    ("2026-06-22T00:00:00", date(2026, 6, 22)),
    ("", None), (None, None), ("aiurea", None),
])
def test_parsarea_datelor_in_toate_formatele(parsing, brut, asteptat):
    assert parsing.parse_date(brut) == asteptat


# ── Factură ──

def test_soldul_si_scadenta(parsing, fx):
    bill = fx("bill")
    assert parsing.bill_amount(bill) == pytest.approx(443.90)
    assert parsing.bill_due_date(bill) == date(2026, 9, 21)
    assert parsing.bill_details(bill)["rest_de_plata"] == pytest.approx(443.90)


# ── Fereastra de autocitire ──

def test_fereastra_reflecta_flagul_din_api(parsing, fx):
    """Starea depinde de ziua rulării — testăm coerența cu flagul, nu o zi anume."""
    window = fx("window_dates")
    flag = window["result"]["Data"]["Is_Window_Open"]
    assert parsing.window_open(window) is (flag == "1")
    details = parsing.window_details(window)
    assert details["zi_deschidere"] == "22"
    assert details["zi_inchidere"] == "26"


@pytest.mark.parametrize("flag,asteptat", [("1", True), ("0", False), ("", False), (None, False)])
def test_ambele_stari_ale_ferestrei(parsing, flag, asteptat):
    resp = {"result": {"Data": {"Is_Window_Open": flag, "OpeningDate": "22", "ClosingDate": "26"}}}
    assert parsing.window_open(resp) is asteptat


# ── Index și consum ──

def test_ultimul_index(parsing, fx):
    hist = fx("meter_read_history")
    assert parsing.latest_index(hist) == pytest.approx(16564)
    details = parsing.latest_index_details(hist)
    assert details["data_citire"] == "2026-06-22"
    assert details["tip_citire"] == "Autocitire"
    assert details["registru"] == "1.8.0"       # energie activă consumată


def test_consumul_dintre_citiri(parsing, fx):
    hist = fx("meter_read_history")
    # 16564 − 16294, între 29.04.2026 și 22.06.2026
    assert parsing.consumption_since_previous(hist) == pytest.approx(270)
    details = parsing.consumption_details(hist)
    assert details["de_la"] == "2026-04-29"
    assert details["pana_la"] == "2026-06-22"
    assert details["zile"] == 54
    assert details["medie_zilnica"] == pytest.approx(5.0, abs=0.01)


def test_citirile_sunt_ordonate_cronologic(parsing):
    """Ordinea din API nu e garantată — sortăm după dată, nu după poziție."""
    resp = {"result": {"Data": [
        {"Date": "22/06/2026", "Index": 16564, "ReadingType": "Autocitire"},
        {"Date": "29/04/2026", "Index": 16294, "ReadingType": "Regularizare"},
    ]}}
    assert parsing.latest_index(resp) == 16564
    assert parsing.consumption_since_previous(resp) == 270


def test_index_in_scadere_nu_produce_consum_negativ(parsing):
    """Schimbare de contor: indexul repornește. Nu raportăm consum negativ."""
    resp = {"result": {"Data": [
        {"Date": "29/04/2026", "Index": 16294},
        {"Date": "22/06/2026", "Index": 12},
    ]}}
    assert parsing.consumption_since_previous(resp) is None


def test_o_singura_citire_nu_da_consum(parsing):
    resp = {"result": {"Data": [{"Date": "22/06/2026", "Index": 16564}]}}
    assert parsing.latest_index(resp) == 16564
    assert parsing.consumption_since_previous(resp) is None
    assert parsing.consumption_details(resp) == {}


# ── Conturi ──

def test_extragerea_conturilor(parsing, fx):
    conturi = parsing.accounts(fx("user_setting"))
    assert conturi and conturi[0]["utility_account_number"]


def test_pod_si_installation_din_pods(parsing, fx):
    pod, inst = parsing.pod_installation(fx("pods"))
    assert pod and inst, "cheile din GetPods sunt `pod` și `installation`, nu `podValue`"


# ── Robustețe ──

@pytest.mark.parametrize("bad", [None, {}, [], "text", {"result": None}, {"result": []}])
def test_totul_tolereaza_raspunsuri_invalide(parsing, bad):
    assert parsing.bill_amount(bad) is None
    assert parsing.bill_due_date(bad) is None
    assert parsing.bill_details(bad) == {}
    assert parsing.window_open(bad) is False
    assert parsing.window_details(bad) == {}
    assert parsing.latest_index(bad) is None
    assert parsing.consumption_since_previous(bad) is None
    assert parsing.accounts(bad) == []
    assert parsing.pod_installation(bad) == ("", "")


# ── Autocitire: construcția entității și verificările de siguranță ──

def test_inregistrarile_citirii_anterioare(parsing, fx):
    records = parsing.previous_read_records(fx("previous_meter_read"))
    assert len(records) == 1                      # un singur registru
    assert records[0]["registerCat"] == "1.8.0"
    assert records[0]["prevMRResult"] == "16294"


def test_entitatea_pastreaza_cheile_originale(parsing, fx):
    """Cheile trebuie să fie IDENTICE cu cele din răspuns — redenumirea rupe apelul."""
    resp = fx("previous_meter_read")
    entities = parsing.build_usage_entities(resp, 16800, "22/08/2026")
    assert len(entities) == 1
    e = entities[0]
    original = parsing.previous_read_records(resp)[0]
    for key in ("contractAccountID", "equipmentNo", "registerNo", "registerType",
                "uom", "preDecimals", "postDecimals", "prevMRResult", "prevMRDate",
                "registerCat", "distributor", "supplier"):
        assert e[key] == original[key], f"cheia {key} nu a fost copiată verbatim"
    assert e["newmeterread"] == "16800"
    assert e["NewMeterReadDate"] == "22/08/2026"
    assert "UtilityAccountNumber" not in e, "cheie redenumită — apelul ar eșua"


def test_valoarea_anterioara_poate_fi_mai_veche_decat_istoricul(parsing, fx):
    """prevMRResult (16294, aprilie) e mai vechi decât ultima autocitire (16564, iunie)."""
    prev = parsing.previous_read_value(fx("previous_meter_read"))
    istoric = parsing.latest_index(fx("meter_read_history"))
    assert prev == 16294
    assert istoric == 16564
    assert prev < istoric, "pragul de validare trebuie luat din istoric, nu din prevMRResult"


# ── Blocaje înainte de trimitere ──

def test_fereastra_inchisa_blocheaza(parsing):
    motiv = parsing.submission_blocker(16800, 16564, window_is_open=False, max_delta=2000)
    assert motiv and "închis" in motiv


def test_index_mai_mic_decat_ultimul_blocheaza(parsing):
    motiv = parsing.submission_blocker(16000, 16564, window_is_open=True, max_delta=2000)
    assert motiv and "înapoi" in motiv


def test_salt_implauzibil_blocheaza(parsing):
    motiv = parsing.submission_blocker(26564, 16564, window_is_open=True, max_delta=2000)
    assert motiv and "implauzibil" in motiv


def test_valoare_lipsa_sau_zero_blocheaza(parsing):
    assert parsing.submission_blocker(None, 16564, True, 2000)
    assert parsing.submission_blocker(0, 16564, True, 2000)


def test_valoare_zecimala_blocheaza(parsing):
    assert parsing.submission_blocker(16800.5, 16564, True, 2000)


def test_valoare_valida_nu_blocheaza(parsing):
    assert parsing.submission_blocker(16800, 16564, True, 2000) is None
    assert parsing.submission_blocker(16564, 16564, True, 2000) is None  # index neschimbat


def test_fara_istoric_cunoscut_nu_blocheaza_pe_prag(parsing):
    """Dacă nu știm ultimul index, nu inventăm un prag — lăsăm API-ul să valideze."""
    assert parsing.submission_blocker(16800, None, True, 2000) is None


# ── Interpretarea răspunsurilor ──

def test_raspuns_de_succes(parsing, fx):
    assert parsing.api_ok(fx("previous_meter_read")) is True


@pytest.mark.parametrize("bad", [None, {}, "x", {"responsestatus": -1, "status_code": 401}])
def test_raspuns_de_eroare(parsing, bad):
    assert parsing.api_ok(bad) is False


def test_mesajul_de_eroare_este_extras(parsing):
    resp = {"error": {"StatusCode": 401, "Message": "Authentication failed."}}
    assert parsing.api_message(resp) == "Authentication failed."


# ── Ultima citire: cine și când ──

def test_data_si_tipul_ultimei_citiri(parsing, fx):
    hist = fx("meter_read_history")
    assert str(parsing.latest_reading_date(hist)) == "2026-06-22"
    assert parsing.latest_reading_type(hist) == "Autocitire"


def test_istoricul_citirilor_cu_tip(parsing, fx):
    istoric = parsing.reading_history(fx("meter_read_history"))
    assert [r["tip"] for r in istoric] == ["Regularizare", "Autocitire"]
    assert [r["data"] for r in istoric] == ["2026-04-29", "2026-06-22"]
    assert istoric[-1]["index"] == 16564


def test_tipul_reflecta_ultima_citire_nu_prima(parsing):
    """Ordinea din API nu e garantată — contează cea mai recentă dată."""
    resp = {"result": {"Data": [
        {"Date": "22/06/2026", "Index": 16564, "ReadingType": "Autocitire"},
        {"Date": "29/04/2026", "Index": 16294, "ReadingType": "Regularizare"},
    ]}}
    assert parsing.latest_reading_type(resp) == "Autocitire"


@pytest.mark.parametrize("bad", [None, {}, [], {"result": {"Data": []}}])
def test_ultima_citire_tolereaza_lipsa_datelor(parsing, bad):
    assert parsing.latest_reading_date(bad) is None
    assert parsing.latest_reading_type(bad) is None
    assert parsing.reading_history(bad) == []


# ── GetMeterValue: getter, nu validator ──

def test_no_record_found_nu_blocheaza(parsing):
    """Starea dinaintea primei autocitiri a lunii — captată pe 22.08.2026.

    Sintetic, nu din fixture: `meter_value` reflectă starea reală a contului și
    se schimbă după fiecare trimitere. Un test legat de conținutul lui ar pica
    la fiecare autocitire.
    """
    resp = {"status_code": 200, "responsestatus": 0,
            "result": {"Message": "No Record Found"}}
    assert parsing.lookup_blocker(resp) is None


def test_fixture_ul_curent_nu_blocheaza_indiferent_de_stare(parsing, fx):
    """Oricare ar fi starea contului acum, un 200 fără eroare nu oprește fluxul."""
    assert parsing.lookup_blocker(fx("meter_value")) is None


def test_eroare_explicita_blocheaza(parsing):
    resp = {"status_code": 401, "responsestatus": -1,
            "error": {"Message": "Authentication failed."}}
    motiv = parsing.lookup_blocker(resp)
    assert motiv and "Authentication failed" in motiv


def test_responsestatus_negativ_blocheaza(parsing):
    motiv = parsing.lookup_blocker({"responsestatus": -1, "result": {"Message": "Invalid"}})
    assert motiv and "Invalid" in motiv


@pytest.mark.parametrize("bad", [None, "text", 42, []])
def test_raspuns_neinterpretabil_blocheaza(parsing, bad):
    assert parsing.lookup_blocker(bad) is not None


def test_raspuns_de_succes_nu_blocheaza(parsing):
    assert parsing.lookup_blocker({"status_code": 200, "responsestatus": 1,
                                   "result": {"Status": 1}}) is None


# ── Indexul declarat pentru perioada curentă ──

def test_indexul_declarat_dupa_trimitere(parsing, fx):
    """Răspunsul real de după trimiterea din 22.08.2026."""
    assert parsing.declared_index(fx("meter_value")) == pytest.approx(16984)


def test_fara_citire_declarata_da_none(parsing):
    """Starea dinaintea trimiterii: responsestatus 0 + „No Record Found"."""
    resp = {"status_code": 200, "responsestatus": 0,
            "result": {"Message": "No Record Found"}}
    assert parsing.declared_index(resp) is None


@pytest.mark.parametrize("bad", [None, {}, "x", {"responsestatus": 1},
                                 {"responsestatus": 1, "result": {"data": None}},
                                 {"responsestatus": 1, "result": {"data": "n/a"}}])
def test_indexul_declarat_tolereaza_raspunsuri_invalide(parsing, bad):
    assert parsing.declared_index(bad) is None


def test_declaratul_difera_de_oficialul_inregistrat(parsing, fx):
    """Cele două surse răspund la întrebări diferite și nu trebuie confundate."""
    declarat = parsing.declared_index(fx("meter_value"))
    oficial = parsing.latest_index(fx("meter_read_history"))
    assert declarat == 16984
    assert oficial == 16564
    assert declarat != oficial, "sursele sunt distincte — declaratul o ia înainte"
