"""Coordonatorul: un ciclu de fetch, din care se servesc toate entitățile."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import parsing
from .api import HidroAuthError, HidroClient, HidroError
from .const import (
    CONF_ACCOUNT,
    CONF_BP_NUMBER,
    CONF_ACCOUNT_NUMBER,
    CONF_INSTALLATION,
    CONF_POD,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class HidroCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Trage datele contului la interval fix."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HidroClient) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.entry = entry
        self.client = client
        self.uan = entry.data[CONF_ACCOUNT]
        self.account = entry.data[CONF_ACCOUNT_NUMBER]
        self.pod = entry.data.get(CONF_POD, "")
        self.installation = entry.data.get(CONF_INSTALLATION, "")
        self.bp_number = entry.data.get(CONF_BP_NUMBER, "")

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            bill, window, history = await asyncio.gather(
                self.client.async_get_bill(self.uan, self.account),
                self.client.async_get_window_dates(self.uan, self.account),
                self.client.async_get_read_history(self.uan, self.pod, self.installation),
            )
        except HidroAuthError as err:
            # Credențialele nu mai sunt valide (parolă schimbată, cont blocat).
            # Re-autentificarea automată din client a fost deja încercată.
            raise ConfigEntryAuthFailed(str(err)) from err
        except HidroError as err:
            # Tranzitoriu: entitățile păstrează ultima valoare cunoscută.
            raise UpdateFailed(str(err)) from err

        # Indexul declarat pentru perioada curentă. Lanțul e mai fragil (are nevoie
        # de citirea anterioară ca să construiască cererea) și poate fi indisponibil
        # în afara ferestrei de autocitire — deci un eșec aici nu are voie să
        # doboare restul datelor.
        declared = None
        try:
            previous = await self.client.async_get_previous_read(
                self.uan, self.pod, self.installation, self.bp_number
            )
            entities = parsing.build_usage_entities(previous, 0, "")
            if entities:
                declared = await self.client.async_validate_meter_value(
                    self.pod, self.installation, self.account, entities
                )
        except HidroError as err:
            _LOGGER.debug("Indexul declarat nu e disponibil: %s", err)

        return {
            "bill": bill,
            "window": window,
            "history": history,
            "declared": declared,
        }
