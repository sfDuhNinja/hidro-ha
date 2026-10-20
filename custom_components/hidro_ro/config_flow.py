"""Config flow: credențiale iHidro, descoperirea contului, reautentificare."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import HidroAuthError, HidroClient, HidroError
from .const import (
    CONF_ACCOUNT,
    CONF_ACCOUNT_NUMBER,
    CONF_BP_NUMBER,
    CONF_INSTALLATION,
    CONF_POD,
    DOMAIN,
)
from .parsing import accounts, pod_installation

_LOGGER = logging.getLogger(__name__)


class HidroConfigFlow(ConfigFlow, domain=DOMAIN):
    """Fluxul de configurare. Fără MFA — un singur pas."""

    VERSION = 1

    def __init__(self) -> None:
        # Nu folosi `_reauth_entry_id`: ConfigFlow îl expune deja ca proprietate
        # read-only, iar o atribuire aici ridică AttributeError.
        self._is_reauth = False
        self._username: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = HidroClient(
                async_get_clientsession(self.hass),
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_login()
                user_setting = await client.async_get_user_setting()
            except HidroAuthError:
                errors["base"] = "invalid_auth"
            except HidroError:
                errors["base"] = "cannot_connect"
            else:
                found = accounts(user_setting)
                if not found:
                    return self.async_abort(reason="no_accounts")
                account = found[0]
                uan = account["utility_account_number"]

                # POD și InstallationNumber vin din GetPods — cheile diferă de cele
                # din GetUserSetting (`pod` / `installation`, nu `podValue`).
                pod, installation = "", ""
                try:
                    pods = await client.async_get_pods(uan, account["account_number"])
                    pod, installation = pod_installation(pods)
                except HidroError:
                    _LOGGER.warning("GetPods a eșuat; istoricul de citiri va lipsi")

                data = {
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_ACCOUNT: uan,
                    CONF_ACCOUNT_NUMBER: account["account_number"],
                    CONF_POD: pod or account.get("pod", ""),
                    CONF_INSTALLATION: installation,
                    CONF_BP_NUMBER: account.get("bp_number", ""),
                }

                if self._is_reauth:
                    entry = self.hass.config_entries.async_get_entry(
                        self.context["entry_id"]
                    )
                    assert entry is not None
                    return self.async_update_reload_and_abort(
                        entry, data={**entry.data, **data}
                    )

                await self.async_set_unique_id(uan)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=f"Hidroelectrica {uan}", data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        self._is_reauth = True
        self._username = entry_data.get(CONF_USERNAME)
        return await self.async_step_user()
