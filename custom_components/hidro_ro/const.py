"""Constante pentru integrarea Hidroelectrica."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "hidro_ro"

API_BASE: Final = "https://ihidro.ro"
LANGUAGE: Final = "RO"
API_TIMEOUT: Final = 30
UPDATE_INTERVAL: Final = 21600  # 6 ore — datele se schimbă cel mult zilnic

# Verificarea TLS rămâne ACTIVĂ. Integrarea upstream o dezactivează (CERT_NONE)
# invocând un certificat problematic; verificat pe 2026-08-19, certificatul
# ihidro.ro e valid (Sectigo OV, expiră 16.03.2027). Prin conexiune trece parola.

PRE_AUTH_HEADERS: Final = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}
POST_AUTH_HEADERS: Final = {**PRE_AUTH_HEADERS, "SourceType": "1"}

EP_GET_ID: Final = "/API/UserLogin/GetId"
EP_VALIDATE: Final = "/API/UserLogin/ValidateUserLogin"
EP_USER_SETTING: Final = "/API/UserLogin/GetUserSetting"
EP_BILL: Final = "/Service/Billing/GetBill"
EP_WINDOW_DATES: Final = "/Service/SelfMeterReading/GetWindowDates"
EP_PODS: Final = "/Service/SelfMeterReading/GetPods"
EP_READ_HISTORY: Final = "/Service/IndexHistory/GetMeterReadHistory"
EP_PREVIOUS_READ: Final = "/Service/SelfMeterReading/GetPreviousMeterRead"
EP_METER_VALUE: Final = "/Service/SelfMeterReading/GetMeterValue"
EP_SUBMIT_READ: Final = "/Service/SelfMeterReading/SubmitSelfMeterRead"
EP_BILLING_HISTORY: Final = "/Service/Billing/GetBillingHistoryList"

CONF_ACCOUNT: Final = "utility_account_number"
CONF_ACCOUNT_NUMBER: Final = "account_number"
CONF_POD: Final = "pod"
CONF_INSTALLATION: Final = "installation"
CONF_BP_NUMBER: Final = "bp_number"

# Marja peste ultimul index dincolo de care o valoare e considerată implauzibilă.
# La ~270 kWh la două luni, 2000 kWh e larg dar prinde greșelile de un digit.
MAX_DELTA_KWH: Final = 2000

# Helper-ul din care butonul citește valoarea de trimis.
INPUT_NUMBER_ENTITY: Final = "input_number.index_hidroelectrica_de_trimis"

# Butonul anunță rezultatul trimiterii; senzorul de status îl ascultă și îl reține.
# Starea aparține entității care o reprezintă, nu coordinatorului — treaba lui e
# să aducă date de la API, nu să țină minte ce a făcut un buton.
SIGNAL_SUBMISSION: Final = "hidro_ro_submission_{entry_id}"

# Registrele contorului. Un prosumator are două: consum și energie injectată.
REG_CONSUMPTION: Final = "1.8.0"
REG_PRODUCTION: Final = "1.8.0_P"
