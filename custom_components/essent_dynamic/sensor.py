"""Sensors for Essent Dynamic prices."""

from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import EssentDayData, EssentDynamicCoordinator, ParsedTariff

_LOGGER = logging.getLogger(__name__)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up sensors via discovery."""

    coordinator: EssentDynamicCoordinator | None = None

    domain_data = hass.data.get(DOMAIN)
    if isinstance(domain_data, dict):
        coordinator = domain_data.get(DATA_COORDINATOR)

    if coordinator is None:
        _LOGGER.debug("Coordinator missing; sensors not added")
        return

    async_add_entities(
        [
            EssentNowPriceSensor(coordinator),
            EssentNextHourPriceSensor(coordinator),
            EssentMinPriceTodaySensor(coordinator),
            EssentMaxPriceTodaySensor(coordinator),
        ],
        update_before_add=True,
    )


def _start_of_hour(local_now: datetime) -> datetime:
    return local_now.replace(minute=0, second=0, microsecond=0)


def _find_next_tariff(data: EssentDayData, now: datetime) -> ParsedTariff | None:
    # Robust approach:
    # - Use tariff start timestamps (sorted) instead of assuming fixed hourly blocks
    # - Pick the first tariff that starts after "now" so gaps/misalignment won't break
    # - Normalize naive/aware datetime comparisons to avoid TypeError
    if not data.tariffs:
        return None

    tariffs = sorted(data.tariffs, key=lambda t: t.start)

    reference_tzinfo = tariffs[0].start.tzinfo
    if reference_tzinfo is None:
        now_cmp = now.replace(tzinfo=None)
    else:
        now_cmp = (
            now if now.tzinfo is not None else now.replace(tzinfo=reference_tzinfo)
        )

    for tariff in tariffs:
        if tariff.start > now_cmp:
            return tariff

    # If the API provided next-day tariffs in the same payload, pick the first of the next day.
    today = now_cmp.date()
    for tariff in tariffs:
        if tariff.start.date() > today:
            return tariff

    # Final fallback: if the API payload contains only past entries, return the last known tariff
    # so the sensor won't become Unavailable while tariffs are still being delivered.
    return tariffs[-1]


def _find_tariff_for_moment(
    data: EssentDayData, moment: datetime
) -> ParsedTariff | None:
    for t in data.tariffs:
        if t.start <= moment < t.end:
            return t
    return None


class _EssentBaseSensor(CoordinatorEntity[EssentDynamicCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EssentDynamicCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def _data(self) -> EssentDayData | None:
        return self.coordinator.data

    @property
    def available(self) -> bool:
        return self._data is not None


class EssentNowPriceSensor(_EssentBaseSensor):
    _attr_unique_id = f"{DOMAIN}_price_now"
    _attr_name = "Essent stroomprijs nu"
    _attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> float | None:
        data = self._data
        if data is None:
            return None

        now = dt_util.as_local(dt_util.now())
        tariff = _find_tariff_for_moment(data, now)
        return tariff.total if tariff else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self._data
        if data is None:
            return {}

        # Requirement: compact list with max 48 items
        compact_tariffs = []
        for t in data.tariffs[:48]:
            compact_tariffs.append(
                {
                    "start": t.start.isoformat(),
                    "end": t.end.isoformat(),
                    "total": t.total,
                    "market": t.market,
                    "fee": t.fee,
                    "tax": t.tax,
                }
            )

        return {
            "vatPercentage": data.vat_percentage,
            "unitOfMeasurement": data.unit_of_measurement,
            "day": data.day.isoformat(),
            "tariffs": compact_tariffs,
        }


class EssentNextHourPriceSensor(_EssentBaseSensor):
    _attr_unique_id = f"{DOMAIN}_price_next_hour"
    _attr_name = "Essent stroomprijs volgend uur"
    _attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> float | None:
        data = self._data
        if data is None:
            return None

        # Use ISO parsing to stay aligned with the API's timezone-naive timestamps.
        now = datetime.fromisoformat(datetime.now().replace(microsecond=0).isoformat())
        if tariff := _find_next_tariff(data, now):
            return tariff.total

        # Only return None when we truly have no usable tariff (prevents Unavailable when data exists).
        return None


class EssentMinPriceTodaySensor(_EssentBaseSensor):
    _attr_unique_id = f"{DOMAIN}_min_today"
    _attr_name = "Essent goedkoopste uur vandaag"
    _attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> float | None:
        data = self._data
        if data is None:
            return None
        return min(t.total for t in data.tariffs)


class EssentMaxPriceTodaySensor(_EssentBaseSensor):
    _attr_unique_id = f"{DOMAIN}_max_today"
    _attr_name = "Essent duurste uur vandaag"
    _attr_native_unit_of_measurement = "EUR/kWh"

    @property
    def native_value(self) -> float | None:
        data = self._data
        if data is None:
            return None
        return max(t.total for t in data.tariffs)
