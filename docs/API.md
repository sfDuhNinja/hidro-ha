# API iHidro

Backend SmartCMobile, proxy `https://ihidro.ro`, header `SourceType: 0` (înainte de
autentificare) și `1` (după).

## Autentificare (fără MFA)

1. `POST /API/UserLogin/GetId` → `key`, `tokenId`
2. `POST /API/UserLogin/ValidateUserLogin` cu `Basic base64(key:tokenId)` → `UserID`, `SessionToken`

Apelurile de date folosesc `Basic base64(UserID:SessionToken)`. Răspunsurile sunt
împachetate ca `{result: {Data: {...}}}`.

| Zonă | Endpoint |
|---|---|
| Conturi | `UserLogin/GetUserSetting` |
| Factură curentă | `Billing/GetBill` |
| Istoric plăți (inclusiv compensații ANRE) | `Billing/GetBillingHistoryList` |
| Consum | `Usage/GetUsageGeneration` |
| Contor | `Usage/GetMultiMeter`, `SelfMeterReading/GetMeterValue` |
| Fereastră autocitire | `SelfMeterReading/GetWindowDates` |
| Istoric citiri | `IndexHistory/GetMeterReadHistory` |
| POD / instalație | `SelfMeterReading/GetPods` |
| Citirea anterioară / trimitere | `SelfMeterReading/GetPreviousMeterRead`, `SubmitSelfMeterRead` |

## Registre

`GetMeterReadHistory` întoarce citirile tuturor registrelor în aceeași listă:
`1.8.0` = energie consumată, `1.8.0_P` = energie injectată (prosumator).

## Compensații ANRE

În `GetBillingHistoryList`, `objBillingPaymentHistoryEntity` conține și încasările, și
compensațiile; compensațiile au `channel` care începe cu `Comp ANRE`.

## Autocitire

`UsageSelfMeterReadEntity` este înregistrarea din `GetPreviousMeterRead` copiată
**verbatim**, cu aceleași chei (`contractAccountID`, nu `UtilityAccountNumber`), plus
`newmeterread` și `NewMeterReadDate` (`DD/MM/YYYY`). O cheie redenumită rupe apelul.

`GetPreviousMeterRead` cere payload propriu (`InstallationNumber`, `podValue`,
`CustomerNumber` = `BpNumber`, `BasicValue`, `Distributor`); cu payload-ul generic
răspunde HTTP 400.

`GetMeterValue` **nu validează** valoarea: e un getter pentru o citire deja înregistrată.
Înainte de o autocitire răspunde 200 cu `"No Record Found"`; cu payload greșit, 400.
Validarea reală se face în `SubmitSelfMeterRead`.

`prevMRResult` este ultima citire oficială a distribuitorului și poate fi mai veche decât
ultima autocitire din istoric; pragul minim se ia din istoric.

## TLS

Integrarea upstream dezactivează validarea certificatului. Aici rămâne activă: certificatul
`ihidro.ro` se validează normal, iar prin conexiune trece parola.
