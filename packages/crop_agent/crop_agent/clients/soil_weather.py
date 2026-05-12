"""
Soil and weather data clients.

SoilGrids (ISRIC) — free, no key, queryable by lat/lon for 14 soil
properties at 250m resolution. Returns pH, N, organic carbon, CEC,
texture, bulk density. We use it to fill missing optional fields.

NASA POWER — free, no key, daily climatology back to 1981. We use it
for GDD calculations and heat/frost-stress windows.
"""
from __future__ import annotations

import logging

import httpx

from ..config import CONFIG

logger = logging.getLogger(__name__)


class SoilGridsClient:
    """ISRIC SoilGrids REST API. Stable, but occasionally slow."""

    async def query_profile(self, lat: float, lon: float) -> dict:
        """
        Returns the topsoil (0-30cm) profile at the coordinate.
        Output: {ph, soc, nitrogen, cec, clay, sand, silt, bulk_density}
        """
        params = {
            "lon": lon,
            "lat": lat,
            "property": ["phh2o", "soc", "nitrogen", "cec", "clay", "sand", "silt", "bdod"],
            "depth": "15-30cm",
            "value": "mean",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logger.debug("SoilGrids query request: %s", params)
                resp = await client.get(CONFIG.soilgrids_base, params=params)
                resp.raise_for_status()
                data = resp.json()
                logger.debug("SoilGrids query response: %s", data)
                return self._flatten(data)
            except (httpx.HTTPError, KeyError) as e:
                logger.warning("SoilGrids query failed: %s — returning empty profile", e)
                return {}

    @staticmethod
    def _flatten(data: dict) -> dict:
        """Pull mean values out of SoilGrids' nested response shape."""
        out = {}
        layers = data.get("properties", {}).get("layers", [])
        for layer in layers:
            name = layer.get("name")
            depths = layer.get("depths", [])
            if not depths:
                continue
            mean = depths[0].get("values", {}).get("mean")
            d_factor = layer.get("unit_measure", {}).get("d_factor", 1)
            if mean is not None and d_factor:
                out[name] = mean / d_factor
        # SoilGrids stores pH×10 — already handled by d_factor, but verify
        return out


class NASAPowerClient:
    """NASA POWER agroclimatology endpoint. Daily values, no key."""

    async def query_daily(
        self,
        lat: float,
        lon: float,
        start: str,  # YYYYMMDD
        end: str,
        parameters: list[str] = None,
    ) -> dict:
        params = {
            "parameters": ",".join(parameters or [
                "T2M_MAX", "T2M_MIN", "T2M",  # temperature
                "PRECTOTCORR",                # precipitation
                "RH2M",                       # humidity
                "ALLSKY_SFC_SW_DWN",          # solar radiation
            ]),
            "community": "AG",
            "longitude": lon,
            "latitude": lat,
            "start": start,
            "end": end,
            "format": "JSON",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                logger.debug("NASA POWER query request: %s", params)
                resp = await client.get(CONFIG.nasa_power_base, params=params)
                resp.raise_for_status()
                data = resp.json()
                logger.debug("NASA POWER query response: %s", data)
                return data.get("properties", {}).get("parameter", {})
            except httpx.HTTPError as e:
                logger.warning("NASA POWER query failed: %s", e)
                return {}

    @staticmethod
    def calculate_gdd(temps_max: list[float], temps_min: list[float], base: float = 10.0) -> float:
        """Growing degree days. base=10°C for most field crops; use 8 for wheat."""
        gdd = 0.0
        for tmax, tmin in zip(temps_max, temps_min):
            mean = (tmax + tmin) / 2
            gdd += max(0.0, mean - base)
        return gdd
