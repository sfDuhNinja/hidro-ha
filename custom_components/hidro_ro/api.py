"""Client HTTP pentru API-ul Hidroelectrica (iHidro).

Autentificare în doi pași, fără MFA:
  1. GetId                → key, tokenId
  2. ValidateUserLogin    → UserID, SessionToken   (Basic base64(key:tokenId))

Apelurile de date folosesc Basic base64(UserID:SessionToken).

Sesiunea expiră selectiv — unele endpoint-uri răspund 401 pe un token care tocmai a
funcționat în altă parte. Cum nu există MFA, re-autentificarea automată e sigură și
invizibilă pentru utilizator (spre deosebire de E.ON, unde ar declanșa coduri SMS).

Verificarea TLS rămâne activă: certificatul ihidro.ro e valid și prin conexiune trece
parola contului.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_BASE,
    API_TIMEOUT,
    EP_BILL,
    EP_BILLING_HISTORY,
    EP_GET_ID,
    EP_PODS,
    EP_METER_VALUE,
    EP_PREVIOUS_READ,
    EP_READ_HISTORY,
    EP_SUBMIT_READ,
    EP_USER_SETTING,
    EP_VALIDATE,
    EP_WINDOW_DATES,
    LANGUAGE,
    POST_AUTH_HEADERS,
    PRE_AUTH_HEADERS,
)

_LOGGER = logging.getLogger(__name__)


class HidroError(Exception):
    """Eroare de comunicare cu API-ul."""


class HidroAuthError(HidroError):
    """Credențiale invalide — e nevoie de intervenția utilizatorului."""


def _basic(user: str, secret: str) -> str:
    return base64.b64encode(f"{user}:{secret}".encode()).decode()


class HidroClient:
    """Client pentru ihidro.ro."""

    def __init__(self, session: ClientSession, username: str, password: str) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._user_id: str | None = None
        self._token: str | None = None
        self._lock = asyncio.Lock()

    @property
    def user_id(self) -> str | None:
        return self._user_id

    async def _post(self, endpoint: str, payload: dict, headers: dict) -> tuple[int, Any]:
        try:
            async with self._session.post(
                f"{API_BASE}{endpoint}", json=payload, headers=headers,
                timeout=API_TIMEOUT,
            ) as resp:
                text = await resp.text()
                try:
                    data = await resp.json(content_type=None) if text.strip() else None
                except ValueError:
                    data = None
                return resp.status, data
        except asyncio.TimeoutError as err:
            raise HidroError(f"Timeout la {endpoint}") from err
        except ClientError as err:
            raise HidroError(f"Eroare de rețea la {endpoint}: {err}") from err

    @staticmethod
    def _data(resp: Any) -> Any:
        if not isinstance(resp, dict):
            return None
        result = resp.get("result")
        return result.get("Data") if isinstance(result, dict) else None

    async def async_login(self) -> None:
        """GetId → ValidateUserLogin."""
        status, resp = await self._post(EP_GET_ID, {}, dict(PRE_AUTH_HEADERS))
        data = self._data(resp) or {}
        key, token_id = data.get("key"), data.get("tokenId")
        if not key or not token_id:
            raise HidroError(f"GetId a eșuat (HTTP {status})")

        now = datetime.now().strftime("%m/%d/%Y %H:%M:%S")
        status, resp = await self._post(EP_VALIDATE, {
            "deviceType": "MobileApp", "OperatingSystem": "Android",
            "UpdatedDate": now, "Deviceid": "", "SessionCode": "",
            "LanguageCode": LANGUAGE, "password": self._password,
            "UserId": self._username, "TFADeviceid": "", "OSVersion": 14,
            "TimeOffSet": "120", "LUpdHideShow": now, "Browser": "NA",
        }, {**PRE_AUTH_HEADERS, "Authorization": f"Basic {_basic(key, token_id)}"})

        table = (self._data(resp) or {}).get("Table") or []
        if not table:
            raise HidroAuthError(f"Autentificare eșuată (HTTP {status})")
        row = table[0]
        self._user_id = row.get("UserID") or ""
        self._token = row.get("SessionToken") or ""
        if not self._user_id or not self._token:
            raise HidroAuthError("Autentificare eșuată — UserID sau SessionToken lipsă")

    def _auth_headers(self) -> dict:
        return {
            **POST_AUTH_HEADERS,
            "Authorization": f"Basic {_basic(self._user_id or '', self._token or '')}",
        }

    async def _ensure_auth(self) -> None:
        """Garantează o sesiune validă ÎNAINTE de construirea payload-ului.

        Payload-urile conțin `UserID`, care e cunoscut abia după login. Dacă se
        construiesc înainte, pleacă cu `UserID: null` și API-ul răspunde 400.
        """
        if self._token:
            return
        async with self._lock:
            if not self._token:
                await self.async_login()

    async def _call(self, endpoint: str, payload: dict) -> Any:
        """POST autentificat, cu o singură re-autentificare la 401."""
        await self._ensure_auth()

        status, data = await self._post(endpoint, payload, self._auth_headers())
        if status == 401:
            _LOGGER.debug("401 la %s — re-autentificare", endpoint)
            async with self._lock:
                await self.async_login()
            status, data = await self._post(endpoint, payload, self._auth_headers())

        if status == 401:
            raise HidroAuthError(f"Acces respins după re-autentificare la {endpoint}")
        if status != 200:
            raise HidroError(f"HTTP {status} la {endpoint}")
        return data

    # ── Endpoint-uri de date ──

    async def async_get_user_setting(self) -> Any:
        await self._ensure_auth()
        return await self._call(EP_USER_SETTING, {"UserID": self._user_id})

    async def async_get_bill(self, uan: str, account: str) -> Any:
        await self._ensure_auth()
        return await self._call(EP_BILL, {
            "LanguageCode": LANGUAGE, "UserID": self._user_id, "IsBillPDF": "0",
            "UtilityAccountNumber": uan, "AccountNumber": account,
        })

    async def async_get_window_dates(self, uan: str, account: str) -> Any:
        await self._ensure_auth()
        return await self._call(EP_WINDOW_DATES, {
            "MeterType": "E", "UserID": self._user_id,
            "UtilityAccountNumber": uan, "AccountNumber": account,
        })

    async def async_get_pods(self, uan: str, account: str) -> Any:
        await self._ensure_auth()
        return await self._call(EP_PODS, {
            "MeterType": "E", "UserID": self._user_id,
            "UtilityAccountNumber": uan, "AccountNumber": account,
        })

    # ── Autocitire (scriere) ──

    async def async_get_previous_read(
        self, uan: str, pod: str, installation: str, customer_number: str
    ) -> Any:
        """Citirea anterioară — baza pentru UsageSelfMeterReadEntity.

        Payload propriu, diferit de restul: cere InstallationNumber, podValue și
        CustomerNumber (= BpNumber din contul utilizatorului). Cu payload-ul
        generic răspunde HTTP 400.
        """
        await self._ensure_auth()
        return await self._call(EP_PREVIOUS_READ, {
            "UtilityAccountNumber": uan,
            "InstallationNumber": installation,
            "podValue": pod,
            "LanguageCode": LANGUAGE,
            "UserID": self._user_id,
            "BasicValue": "",
            "CustomerNumber": customer_number,
            "Distributor": "",
        })

    async def async_validate_meter_value(
        self, pod: str, installation: str, account: str, entities: list[dict]
    ) -> Any:
        """Validarea Hidroelectrica, ÎNAINTE de trimitere."""
        await self._ensure_auth()
        return await self._call(EP_METER_VALUE, {
            "UserId": self._user_id,
            "podValue": pod,
            "InstallationNumber": installation,
            "AccountNumber": account,
            "UsageSelfMeterReadEntity": entities,
        })

    async def async_submit_read(
        self, pod: str, installation: str, account: str, entities: list[dict]
    ) -> Any:
        """Trimite autocitirea. IREVERSIBIL — apelează doar după validare."""
        await self._ensure_auth()
        return await self._call(EP_SUBMIT_READ, {
            "UserId": self._user_id,
            "podValue": pod,
            "InstallationNumber": installation,
            "AccountNumber": account,
            "UsageSelfMeterReadEntity": entities,
        })

    async def async_get_read_history(self, uan: str, pod: str, installation: str) -> Any:
        await self._ensure_auth()
        return await self._call(EP_READ_HISTORY, {
            "utilityAccountNumber": uan, "podValue": pod,
            "LanguageCode": LANGUAGE, "InstallationNumber": installation,
            "SerialNumber": [],
        })

    async def async_get_billing_history(self, uan: str, account: str) -> Any:
        """Plățile, inclusiv compensațiile ANRE ale prosumatorilor."""
        await self._ensure_auth()
        return await self._call(EP_BILLING_HISTORY, {
            "LanguageCode": LANGUAGE, "UserID": self._user_id,
            "UtilityAccountNumber": uan, "AccountNumber": account,
            "FromDate": "", "ToDate": "",
        })
