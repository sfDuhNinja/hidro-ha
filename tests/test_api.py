"""Clientul API — cazul care a picat în producție pe 2026-08-21.

Payload-urile conțin `UserID`, cunoscut abia după login. Dacă se construiesc
înainte de autentificare, pleacă cu `UserID: null` și API-ul răspunde HTTP 400
(„Configurare eșuată: HTTP 400 la /Service/Billing/GetBill").
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / "custom_components" / "hidro_ro"

_PKG = "hidro_api_pure"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [str(COMPONENT)]
    sys.modules[_PKG] = pkg
    for name in ("const", "api"):
        spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", COMPONENT / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{_PKG}.{name}"] = mod
        spec.loader.exec_module(mod)

api = sys.modules[f"{_PKG}.api"]


class FakeResponse:
    def __init__(self, status, payload):
        self.status, self._payload = status, payload

    async def text(self):
        return "{}"

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Răspunde la fluxul de login și înregistrează fiecare cerere."""

    def __init__(self, extra=None):
        self.calls = []
        self._extra = list(extra or [])

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json))
        if url.endswith("/GetId"):
            return FakeResponse(200, {"result": {"Data": {"key": "k", "tokenId": "t"}}})
        if url.endswith("/ValidateUserLogin"):
            return FakeResponse(200, {"result": {"Data": {"Table": [
                {"UserID": "USER-42", "SessionToken": "SESS"}]}}})
        if self._extra:
            return FakeResponse(*self._extra.pop(0))
        return FakeResponse(200, {"result": {"Data": {}}})

    def payload_for(self, suffix):
        for url, payload in self.calls:
            if url.endswith(suffix):
                return payload
        return None


@pytest.mark.asyncio
async def test_getbill_trimite_userid_real_nu_null():
    """Regresie: payload-ul se construia înainte de login → UserID: null → 400."""
    session = FakeSession()
    client = api.HidroClient(session, "u", "p")

    await client.async_get_bill("UAN1", "ACC1")

    payload = session.payload_for("/GetBill")
    assert payload is not None, "GetBill nu a fost apelat"
    assert payload["UserID"] == "USER-42", (
        f"UserID trimis: {payload['UserID']!r} — payload construit înainte de login"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("metoda,args,suffix", [
    ("async_get_user_setting", (), "/GetUserSetting"),
    ("async_get_bill", ("UAN1", "ACC1"), "/GetBill"),
    ("async_get_window_dates", ("UAN1", "ACC1"), "/GetWindowDates"),
    ("async_get_pods", ("UAN1", "ACC1"), "/GetPods"),
])
async def test_niciun_payload_nu_pleaca_cu_userid_gol(metoda, args, suffix):
    session = FakeSession()
    client = api.HidroClient(session, "u", "p")
    await getattr(client, metoda)(*args)
    payload = session.payload_for(suffix)
    assert payload.get("UserID") == "USER-42"


@pytest.mark.asyncio
async def test_loginul_se_face_o_singura_data():
    session = FakeSession()
    client = api.HidroClient(session, "u", "p")
    await client.async_get_bill("UAN1", "ACC1")
    await client.async_get_window_dates("UAN1", "ACC1")
    assert sum(1 for u, _ in session.calls if u.endswith("/GetId")) == 1


@pytest.mark.asyncio
async def test_401_declanseaza_reautentificare_si_reincercare():
    session = FakeSession(extra=[(401, None), (200, {"result": {"Data": {"ok": 1}}})])
    client = api.HidroClient(session, "u", "p")
    result = await client.async_get_bill("UAN1", "ACC1")
    assert result == {"result": {"Data": {"ok": 1}}}
    assert sum(1 for u, _ in session.calls if u.endswith("/GetId")) == 2


@pytest.mark.asyncio
async def test_credentiale_invalide_dau_eroare_de_autentificare():
    class NoTable(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            self.calls.append((url, json))
            if url.endswith("/GetId"):
                return FakeResponse(200, {"result": {"Data": {"key": "k", "tokenId": "t"}}})
            return FakeResponse(200, {"result": {"Data": {"Table": []}}})

    client = api.HidroClient(NoTable(), "u", "gresit")
    with pytest.raises(api.HidroAuthError):
        await client.async_login()
