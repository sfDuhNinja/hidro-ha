"""Butonul de autocitire — singura operație din integrare care SCRIE undeva.

Un index trimis devine bază de facturare, iar corectarea trece prin relația cu
furnizorul, nu printr-un buton. De aceea fluxul e conservator:

  1. verificări locale (fereastră, prag, plauzibilitate) — înainte de orice apel
  2. GetPreviousMeterRead proaspăt — structura contorului se poate schimba lunar
  3. GetMeterValue — validarea Hidroelectrica; dacă pică, NU trimitem
  4. SubmitSelfMeterRead — abia acum pleacă efectiv

Fără retry automat: la eșec parțial nu știm dacă serverul a înregistrat, deci
raportăm și lăsăm decizia omului.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import parsing
from .api import HidroError
from .const import DOMAIN, INPUT_NUMBER_ENTITY, MAX_DELTA_KWH, SIGNAL_SUBMISSION
from .coordinator import HidroCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HidroCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HidroSubmitReadButton(coordinator)])


class HidroSubmitReadButton(CoordinatorEntity[HidroCoordinator], ButtonEntity):
    """Trimite indexul din `input_number` către Hidroelectrica."""

    _attr_has_entity_name = True
    _attr_name = "Trimite indexul"
    _attr_icon = "mdi:send-check"

    def __init__(self, coordinator: HidroCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.uan}_trimite_index"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.uan)},
            manufacturer="Hidroelectrica",
            name=f"Hidroelectrica {coordinator.uan}",
        )

    @property
    def available(self) -> bool:
        """Disponibil doar cât fereastra de autocitire e deschisă."""
        data = self.coordinator.data or {}
        # Prosumatorii nu autocitesc: contorul bidirecțional e citit de distribuitor.
        return (
            super().available
            and parsing.window_open(data.get("window"))
            and not parsing.is_prosumer(data.get("history"))
        )

    def _record(self, rezultat: dict[str, Any]) -> None:
        """Anunță senzorul de status. El deține și persistă starea."""
        async_dispatcher_send(
            self.hass,
            SIGNAL_SUBMISSION.format(entry_id=self.coordinator.entry.entry_id),
            rezultat,
        )

    async def _fail(self, motiv: str) -> None:
        """Oprește fluxul, notifică și reține motivul."""
        _LOGGER.warning("Autocitire oprită: %s", motiv)
        self._record({
            "stare": "eroare",
            "mesaj": motiv,
            "moment": datetime.now().isoformat(timespec="seconds"),
        })
        await self.hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Autocitire netrimisă",
                "message": motiv,
                "notification_id": "hidro_autocitire",
            },
            blocking=False,
        )

    async def async_press(self) -> None:
        data = self.coordinator.data or {}

        # ── 1. Verificări locale ──
        if parsing.is_prosumer(data.get("history")):
            await self._fail("Contul e de prosumator: autocitirea nu se face din integrare.")
            return
        state = self.hass.states.get(INPUT_NUMBER_ENTITY)
        if state is None:
            await self._fail(f"Lipsește {INPUT_NUMBER_ENTITY}.")
            return
        try:
            new_value = float(state.state)
        except (TypeError, ValueError):
            await self._fail(f"Valoare invalidă în {INPUT_NUMBER_ENTITY}: {state.state!r}")
            return

        motiv = parsing.submission_blocker(
            new_value=new_value,
            last_index=parsing.latest_index(data.get("history")),
            window_is_open=parsing.window_open(data.get("window")),
            max_delta=MAX_DELTA_KWH,
        )
        if motiv:
            await self._fail(motiv)
            return

        coord = self.coordinator
        bp_number = coord.bp_number

        try:
            # ── 2. Citirea anterioară, proaspătă ──
            previous = await coord.client.async_get_previous_read(
                coord.uan, coord.pod, coord.installation, bp_number
            )
            entities = parsing.build_usage_entities(
                previous, int(new_value), datetime.now().strftime("%d/%m/%Y")
            )
            if not entities:
                await self._fail(
                    "Hidroelectrica nu a returnat citirea anterioară — "
                    "nu pot construi cererea. Încearcă mai târziu."
                )
                return

            # ── 3. Test de fum: identificatorii sunt acceptați? ──
            # NU e o validare a valorii — vezi parsing.lookup_blocker. Un payload
            # greșit primește 400 (ridicat ca HidroError de _call); un 200 cu
            # "No Record Found" e normal înainte de prima autocitire a lunii.
            lookup = await coord.client.async_validate_meter_value(
                coord.pod, coord.installation, coord.account, entities
            )
            motiv_lookup = parsing.lookup_blocker(lookup)
            if motiv_lookup:
                await self._fail(motiv_lookup)
                return

            # ── 4. Trimitere ──
            raspuns = await coord.client.async_submit_read(
                coord.pod, coord.installation, coord.account, entities
            )
        except HidroError as err:
            await self._fail(
                f"Eroare de comunicare: {err}. "
                "NU se reîncearcă automat — verifică în aplicația Hidroelectrica "
                "dacă citirea a fost totuși înregistrată."
            )
            return

        if not parsing.api_ok(raspuns):
            mesaj = parsing.api_message(raspuns) or "motiv necomunicat"
            await self._fail(f"Trimiterea a eșuat: {mesaj}")
            return

        self._record({
            "stare": "trimis",
            "index": int(new_value),
            "mesaj": parsing.api_message(raspuns) or "Trimis cu succes.",
            "moment": datetime.now().isoformat(timespec="seconds"),
        })
        await self.hass.services.async_call(
            "persistent_notification", "create",
            {
                "title": "Index trimis",
                "message": f"Indexul {int(new_value)} kWh a fost trimis la Hidroelectrica.",
                "notification_id": "hidro_autocitire",
            },
            blocking=False,
        )
        await coord.async_request_refresh()
