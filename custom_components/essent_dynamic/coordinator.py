"""DataUpdateCoordinator for Essent Dynamic prices."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import API_URL, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedTariff:
    start: datetime
    end: datetime
    total: float
    market: float | None
    fee: float | None
    tax: float | None


@dataclass(frozen=True)
class EssentDayData:
    day: date
    vat_percentage: float | int | None
    unit_of_measurement: str | None
    tariffs: list[ParsedTariff]


class EssentDynamicCoordinator(DataUpdateCoordinator[EssentDayData | None]):
    """Coordinator that fetches Essent dynamic hourly prices."""

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self) -> EssentDayData | None:
        """Fetch and parse data from Essent.

        Requirement: do not crash HA when schema is missing.
        Return None when required fields are missing.
        """

        try:
            async with self._session.get(API_URL, timeout=30) as resp:
                resp.raise_for_status()
                payload: Any = await resp.json()
        except Exception as exc:
            _LOGGER.debug("Failed fetching Essent prices: %s", exc)
            return None

        prices = payload.get("prices") if isinstance(payload, dict) else None
        if not isinstance(prices, list) or not prices:
            _LOGGER.debug("Essent payload missing/invalid 'prices' list")
            return None

        today = dt_util.now().date()
        chosen: dict[str, Any] | None = None

        for entry in prices:
            if not isinstance(entry, dict):
                continue
            if entry.get("date") == today.isoformat():
                chosen = entry
                break

        if chosen is None:
            first = prices[0]
            if not isinstance(first, dict):
                _LOGGER.debug("Essent payload 'prices[0]' is not an object")
                return None
            chosen = first

        day_str = chosen.get("date")
        try:
            day = date.fromisoformat(day_str) if isinstance(day_str, str) else today
        except ValueError:
            _LOGGER.debug("Essent payload has invalid day string: %s", day_str)
            day = today

        electricity = chosen.get("electricity") if isinstance(chosen, dict) else None
        if not isinstance(electricity, dict):
            _LOGGER.debug("Essent payload missing 'electricity' object for day=%s", day_str)
            return None

        unit = electricity.get("unitOfMeasurement")
        vat = electricity.get("vatPercentage")

        tariffs_raw = electricity.get("tariffs")
        if not isinstance(tariffs_raw, list) or not tariffs_raw:
            _LOGGER.debug("Essent payload missing/invalid 'tariffs' list for day=%s", day_str)
            return None

        parsed_tariffs: list[ParsedTariff] = []

        for t in tariffs_raw:
            if not isinstance(t, dict):
                continue

            start_str = t.get("startDateTime")
            end_str = t.get("endDateTime")
            total = t.get("totalAmount")

            if not isinstance(start_str, str) or not isinstance(end_str, str) or total is None:
                _LOGGER.debug("Tariff missing start/end/total fields; skipping")
                continue

            try:
                # Requirement: ISO without timezone, parse via datetime.fromisoformat
                start = datetime.fromisoformat(start_str)
                end = datetime.fromisoformat(end_str)
            except ValueError:
                _LOGGER.debug("Invalid start/end datetime format; skipping")
                continue

            # Parse group amounts
            market = fee = tax = None
            groups = t.get("groups")
            if isinstance(groups, list):
                by_type: dict[str, Any] = {}
                for g in groups:
                    if isinstance(g, dict) and isinstance(g.get("type"), str):
                        by_type[g["type"]] = g.get("amount")

                market = by_type.get("MARKET_PRICE") if isinstance(by_type.get("MARKET_PRICE"), (int, float)) else None
                fee = by_type.get("PURCHASING_FEE") if isinstance(by_type.get("PURCHASING_FEE"), (int, float)) else None
                tax = by_type.get("TAX") if isinstance(by_type.get("TAX"), (int, float)) else None

            if not isinstance(total, (int, float)):
                _LOGGER.debug("Tariff totalAmount is not numeric; skipping")
                continue

            parsed_tariffs.append(
                ParsedTariff(
                    start=start,
                    end=end,
                    total=float(total),
                    market=float(market) if isinstance(market, (int, float)) else None,
                    fee=float(fee) if isinstance(fee, (int, float)) else None,
                    tax=float(tax) if isinstance(tax, (int, float)) else None,
                )
            )

        if not parsed_tariffs:
            _LOGGER.debug("No valid tariffs parsed for day=%s", day_str)
            return None

        parsed_tariffs.sort(key=lambda x: x.start)

        return EssentDayData(
            day=day,
            vat_percentage=vat if isinstance(vat, (int, float)) else None,
            unit_of_measurement=unit if isinstance(unit, str) else None,
            tariffs=parsed_tariffs,
        )
