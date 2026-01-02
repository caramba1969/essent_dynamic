"""Essent Dynamic custom integration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.discovery import async_load_platform

from .const import DATA_COORDINATOR, DOMAIN
from .coordinator import EssentDynamicCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Essent Dynamic integration.

    No YAML config required: we always load the sensor platform via discovery.
    """

    hass.data.setdefault(DOMAIN, {})

    coordinator = EssentDynamicCoordinator(hass)
    hass.data[DOMAIN][DATA_COORDINATOR] = coordinator

    # Prime the coordinator, but never crash HA if the API/schema is missing.
    await coordinator.async_refresh()

    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))

    _LOGGER.debug("Essent Dynamic setup complete")
    return True
