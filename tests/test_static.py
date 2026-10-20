"""Verificări statice — clase de erori pe care testele pe fixture-uri nu le prind.

Ambele au fost întâlnite în producție la integrarea E.ON, pe 2026-08-19:
un atribut care calcă peste o proprietate read-only din ConfigFlow, și o
combinație device_class/state_class respinsă de HA.
"""

import ast
from pathlib import Path

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "hidro_ro"

REZERVATE = {
    "_reauth_entry_id", "_reconfigure_entry_id", "context", "cur_step",
    "flow_id", "handler", "hass", "init_data", "source", "unique_id",
}

COMBINATII_PERMISE = {
    "ENERGY": {"TOTAL", "TOTAL_INCREASING"},
    "MONETARY": {"TOTAL", "TOTAL_INCREASING"},
    "TIMESTAMP": set(),          # TIMESTAMP nu acceptă state_class
}


def _atribute_config_flow() -> set[str]:
    tree = ast.parse((COMPONENT / "config_flow.py").read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                found.add(t.attr)
    return found


def _descrieri() -> list[dict[str, str]]:
    tree = ast.parse((COMPONENT / "sensor.py").read_text())
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HidroSensorDescription"):
            continue
        item: dict[str, str] = {}
        for kw in node.keywords:
            if kw.arg in {"key", "device_class", "state_class"}:
                if isinstance(kw.value, ast.Constant):
                    item[kw.arg] = str(kw.value.value)
                elif isinstance(kw.value, ast.Attribute):
                    item[kw.arg] = kw.value.attr
        out.append(item)
    return out


def test_config_flow_nu_scrie_peste_atribute_rezervate():
    coliziuni = _atribute_config_flow() & REZERVATE
    assert not coliziuni, f"nume rezervate de ConfigFlow: {sorted(coliziuni)}"


def test_combinatiile_device_class_state_class_sunt_valide():
    erori = []
    for d in _descrieri():
        dc, sc = d.get("device_class"), d.get("state_class")
        if dc is None:
            continue
        permise = COMBINATII_PERMISE.get(dc)
        if permise is None:
            continue
        if sc is None:
            continue
        if sc not in permise:
            erori.append(f"{d.get('key')}: {dc} + {sc} (permise: {sorted(permise) or 'niciuna'})")
    assert not erori, "combinații respinse de HA:\n  " + "\n  ".join(erori)


def test_cheile_senzorilor_sunt_unice():
    chei = [d["key"] for d in _descrieri() if "key" in d]
    # Numărul e intenționat fix: un senzor nou trebuie observat, nu strecurat.
    assert len(chei) == 10, f"așteptam 10 senzori (7 + 3 de prosumator), am {len(chei)}: {chei}"
    assert len(chei) == len(set(chei)), f"chei duplicate: {chei}"


def test_toate_fisierele_compileaza():
    for path in sorted(COMPONENT.glob("*.py")):
        ast.parse(path.read_text(), filename=str(path))


# ── Butonul de autocitire: proprietăți de siguranță verificate în cod ──
#
# Fluxul nu poate fi rulat în teste fără Home Assistant, dar ordinea apelurilor
# și absența retry-ului sunt verificabile static — și sunt exact lucrurile care
# nu au voie să regreseze la o refactorizare.

def _sursa_buton() -> str:
    return (COMPONENT / "button.py").read_text()


def _corp_async_press() -> ast.AsyncFunctionDef:
    tree = ast.parse(_sursa_buton())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_press":
            return node
    raise AssertionError("async_press nu există în button.py")


def _ordinea_apelurilor() -> list[str]:
    urmarite = {
        "async_get_previous_read", "async_validate_meter_value",
        "async_submit_read", "submission_blocker",
    }
    gasite = []
    for node in ast.walk(_corp_async_press()):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in urmarite:
                gasite.append((node.lineno, node.func.attr))
    return [nume for _, nume in sorted(gasite)]


def test_validarea_precede_trimiterea():
    """Invariantul central: nu se trimite nimic ce n-a trecut GetMeterValue."""
    ordine = _ordinea_apelurilor()
    assert "async_submit_read" in ordine, "butonul nu trimite nimic?"
    assert "async_validate_meter_value" in ordine, "lipsește validarea server-side"
    assert ordine.index("async_validate_meter_value") < ordine.index("async_submit_read"), (
        f"trimiterea are loc înaintea validării: {ordine}"
    )


def test_verificarile_locale_sunt_primele():
    ordine = _ordinea_apelurilor()
    assert ordine[0] == "submission_blocker", (
        f"verificările locale nu sunt primele: {ordine}"
    )


def test_citirea_anterioara_este_proaspata():
    """Structura contorului se ia la fiecare apăsare, nu din cache."""
    ordine = _ordinea_apelurilor()
    assert ordine.index("async_get_previous_read") < ordine.index("async_validate_meter_value")


def test_fara_retry_automat():
    """Un eșec parțial nu se reîncearcă — nu știm dacă serverul a înregistrat."""
    for node in ast.walk(_corp_async_press()):
        assert not isinstance(node, (ast.While, ast.For, ast.AsyncFor)), (
            "buclă în async_press — trimiterea nu are voie să se reîncerce automat"
        )


def test_butonul_e_indisponibil_cu_fereastra_inchisa():
    sursa = _sursa_buton()
    assert "def available" in sursa, "lipsește gardul de disponibilitate"
    assert "window_open" in sursa, "disponibilitatea nu ține cont de fereastră"


# ── Unde trăiește starea ultimei trimiteri ──

def test_senzorul_de_status_supravietuieste_repornirii():
    """Starea trebuie restaurată, altfel o repornire ar permite o a doua trimitere."""
    sursa = (COMPONENT / "sensor.py").read_text()
    assert "RestoreEntity" in sursa, "senzorul de status nu-și restaurează starea"
    assert "async_get_last_state" in sursa, "restaurarea nu e efectiv citită"


def test_coordinatorul_nu_tine_starea_trimiterii():
    """Coordinatorul aduce date de la API; nu ține minte ce a făcut un buton."""
    sursa = (COMPONENT / "coordinator.py").read_text()
    assert "last_submission" not in sursa, (
        "starea trimiterii s-a întors în coordinator — se pierde la repornire"
    )


def test_butonul_nu_scrie_direct_in_alta_entitate():
    """Comunicarea buton → senzor trece prin dispatcher, nu prin atribute partajate."""
    sursa = (COMPONENT / "button.py").read_text()
    assert "async_dispatcher_send" in sursa
    assert "last_submission" not in sursa
