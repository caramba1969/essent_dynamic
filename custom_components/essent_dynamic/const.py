"""Constants for the Essent Dynamic integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "essent_dynamic"

API_URL = "https://www.essent.nl/api/public/tariffmanagement/dynamic-prices/v1/"

UPDATE_INTERVAL = timedelta(minutes=10)

DATA_COORDINATOR = "coordinator"
