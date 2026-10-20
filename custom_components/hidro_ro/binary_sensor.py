"""Senzor binar pentru fereastra de autocitire."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import parsing
from .const import DOMAIN
from .coordinator import HidroCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HidroCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HidroReadingWindow(coordinator)])


class HidroReadingWindow(CoordinatorEntity[HidroCoordinator], BinarySensorEntity):
    """`on` cât timp Hidroelectrica acceptă autocitirea.

    Contorul nu e inteligent, deci indexul se mișcă doar când trimiți o citire —
    fereastra e semnalul că se poate.
    """

    _attr_has_entity_name = True
    _attr_name = "Fereastră autocitire"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator: HidroCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.uan}_fereastra_autocitire"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.uan)},
            manufacturer="Hidroelectrica",
            name=f"Hidroelectrica {coordinator.uan}",
        )

    @property
    def is_on(self) -> bool:
        return parsing.window_open((self.coordinator.data or {}).get("window"))

    @property
    def extra_state_attributes(self) -> dict | None:
        return parsing.window_details((self.coordinator.data or {}).get("window")) or None
