"""Senzorii Hidroelectrica."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import parsing
from .const import DOMAIN, REG_PRODUCTION, SIGNAL_SUBMISSION
from .coordinator import HidroCoordinator

_TZ = ZoneInfo("Europe/Bucharest")


def _reading_datetime(data: dict[str, Any]) -> datetime | None:
    """Data ultimei citiri, ca datetime cu fus orar."""
    when = parsing.latest_reading_date(data.get("history"))
    return datetime.combine(when, time.min, tzinfo=_TZ) if when else None


def _due_datetime(data: dict[str, Any]) -> datetime | None:
    """Scadența ca datetime cu fus orar — cerut de device_class TIMESTAMP."""
    due = parsing.bill_due_date(data.get("bill"))
    return datetime.combine(due, time.min, tzinfo=_TZ) if due else None


@dataclass(frozen=True, kw_only=True)
class HidroSensorDescription(SensorEntityDescription):
    """Descriere de senzor cu extractoarele proprii."""

    value_fn: Callable[[dict[str, Any]], Any]
    attrs_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORS: tuple[HidroSensorDescription, ...] = (
    HidroSensorDescription(
        key="sold",
        translation_key="sold",
        name="Sold de plată",
        native_unit_of_measurement="RON",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: parsing.bill_amount(d.get("bill")),
        attrs_fn=lambda d: parsing.bill_details(d.get("bill")),
    ),
    HidroSensorDescription(
        key="scadenta",
        translation_key="scadenta",
        name="Scadență",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_due_datetime,
    ),
    HidroSensorDescription(
        key="index",
        translation_key="index",
        name="Index contor",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: parsing.latest_index(d.get("history")),
        attrs_fn=lambda d: parsing.latest_index_details(d.get("history")),
    ),
    HidroSensorDescription(
        key="ultima_citire",
        translation_key="ultima_citire",
        name="Ultima citire",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_reading_datetime,
        attrs_fn=lambda d: {
            "tip": parsing.latest_reading_type(d.get("history")),
            "index": parsing.latest_index(d.get("history")),
            "registru": (parsing.latest_index_details(d.get("history")) or {}).get("registru"),
            "istoric": parsing.reading_history(d.get("history")),
        },
    ),
    HidroSensorDescription(
        key="tip_ultima_citire",
        translation_key="tip_ultima_citire",
        name="Tip ultima citire",
        icon="mdi:account-check-outline",
        value_fn=lambda d: parsing.latest_reading_type(d.get("history")),
        attrs_fn=lambda d: {
            "data": str(parsing.latest_reading_date(d.get("history")) or ""),
        },
    ),
    HidroSensorDescription(
        key="index_declarat",
        translation_key="index_declarat",
        name="Index declarat",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        # Ce ai declarat pentru perioada curentă — apare imediat după trimitere.
        # `index_contor` rămâne ce a înregistrat oficial Hidroelectrica.
        value_fn=lambda d: parsing.declared_index(d.get("declared")),
    ),
    HidroSensorDescription(
        key="consum_ultima_perioada",
        translation_key="consum_ultima_perioada",
        name="Consum ultima perioadă",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        # Singura măsură de consum disponibilă: contorul nu e inteligent, deci
        # Hidroelectrica nu expune o curbă de consum pentru acest loc.
        value_fn=lambda d: parsing.consumption_since_previous(d.get("history")),
        attrs_fn=lambda d: parsing.consumption_details(d.get("history")),
    ),
)


# Doar pentru prosumator — vezi `parsing.is_prosumer`.
PROSUMER_SENSORS: tuple[HidroSensorDescription, ...] = (
    HidroSensorDescription(
        key="index_produs",
        translation_key="index_produs",
        name="Index energie produsă",
        icon="mdi:solar-power-variant",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda d: parsing.latest_index(d.get("history"), REG_PRODUCTION),
        attrs_fn=lambda d: parsing.latest_index_details(d.get("history"), REG_PRODUCTION),
    ),
    HidroSensorDescription(
        key="productie_ultima_perioada",
        translation_key="productie_ultima_perioada",
        name="Producție ultima perioadă",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: parsing.consumption_since_previous(d.get("history"), REG_PRODUCTION),
        attrs_fn=lambda d: parsing.consumption_details(d.get("history"), REG_PRODUCTION),
    ),
    HidroSensorDescription(
        key="compensatii_anre",
        translation_key="compensatii_anre",
        name="Compensații ANRE primite",
        icon="mdi:cash-plus",
        native_unit_of_measurement="RON",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d: parsing.compensation_total(d.get("billing_history")),
        attrs_fn=lambda d: parsing.compensation_details(d.get("billing_history")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: HidroCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [HidroSensor(coordinator, desc) for desc in SENSORS]
    if parsing.is_prosumer(coordinator.data.get("history")):
        entities += [HidroSensor(coordinator, desc) for desc in PROSUMER_SENSORS]
    else:
        # Cont nou: registrul de producție apare abia după prima citire. Când
        # apare, reîncarcă integrarea ca să se creeze senzorii de prosumator.
        @callback
        def _reload_if_prosumer() -> None:
            if parsing.is_prosumer((coordinator.data or {}).get("history")):
                hass.config_entries.async_schedule_reload(entry.entry_id)

        entry.async_on_unload(coordinator.async_add_listener(_reload_if_prosumer))
    entities.append(HidroLastSubmissionSensor(coordinator))
    async_add_entities(entities)


class HidroLastSubmissionSensor(
    CoordinatorEntity[HidroCoordinator], SensorEntity, RestoreEntity
):
    """Rezultatul ultimei autocitiri trimise.

    Un `button` din HA nu poate întoarce nimic în interfață. Pentru o operație
    ireversibilă asta e inacceptabil, deci rezultatul trăiește aici — în entitatea
    care îl reprezintă, nu în coordinator.

    Starea supraviețuiește repornirilor prin RestoreEntity: HA o salvează în
    `.storage/core.restore_state`, independent de recorder. Contează, pentru că
    `binary_sensor.index_hidroelectrica_dat_luna_curenta` se bazează pe atributul
    `moment` ca să știe dacă indexul a fost deja trimis luna curentă — fără
    restaurare, o repornire ar face butonul de navigare să reapară și ai putea
    trimite de două ori.
    """

    _attr_has_entity_name = True
    _attr_name = "Ultima trimitere"
    _attr_icon = "mdi:file-send-outline"

    def __init__(self, coordinator: HidroCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.uan}_ultima_trimitere"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.uan)},
            manufacturer="Hidroelectrica",
            name=f"Hidroelectrica {coordinator.uan}",
        )
        self._stare: str = "niciuna"
        self._detalii: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        # Recuperează ce era înainte de repornire.
        last = await self.async_get_last_state()
        if last is not None and last.state not in (None, "", "unknown", "unavailable"):
            self._stare = last.state
            self._detalii = {
                k: v for k, v in last.attributes.items()
                if k not in ("friendly_name", "icon", "device_class")
            }

        # Ascultă rezultatele raportate de buton.
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_SUBMISSION.format(entry_id=self.coordinator.entry.entry_id),
                self._handle_submission,
            )
        )

    @callback
    def _handle_submission(self, rezultat: dict[str, Any]) -> None:
        self._stare = rezultat.get("stare", "niciuna")
        self._detalii = dict(rezultat)
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        return self._stare

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return dict(self._detalii) or None


class HidroSensor(CoordinatorEntity[HidroCoordinator], SensorEntity):
    """Senzor care citește exclusiv din datele coordonatorului (fără I/O propriu)."""

    entity_description: HidroSensorDescription
    _attr_has_entity_name = True

    def __init__(self, coordinator: HidroCoordinator, description: HidroSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.uan}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.uan)},
            manufacturer="Hidroelectrica",
            name=f"Hidroelectrica {coordinator.uan}",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.entity_description.attrs_fn:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data or {}) or None
