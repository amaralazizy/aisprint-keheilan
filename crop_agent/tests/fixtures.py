"""Sample inputs for tests and local debugging."""
from __future__ import annotations

from datetime import date

from ..models import RawInput, WaterSource


def sample_sharqia_winter() -> RawInput:
    """Smallholder in Sharqia, winter wheat season, no measured soil."""
    return RawInput(
        target_crop="wheat",
        latitude=31.11071505258177,
        longitude=32.12081264010078,
        area_feddan=5.0,
        water_source=WaterSource.NILE_CANAL,
        soil_type="clay",
        budget_egp=25000,
        start_date=date(2026, 11, 15),
        harvest_horizon_days=180,
        language="en",
    )


def sample_minya_water_stress() -> RawInput:
    """Minya farmer post-GERD, water-scarce, with measured soil."""
    return RawInput(
        target_crop="maize",
        latitude=28.10,
        longitude=30.75,
        area_feddan=3.0,
        water_source=WaterSource.NILE_CANAL,
        soil_type="sandy loam",
        budget_egp=15000,
        start_date=date(2026, 11, 1),
        harvest_horizon_days=180,
        language="ar",
        ph=7.8,
        nitrogen_ppm=20,
        salinity_ds_m=2.5,
        cec=8,
    )


def sample_salinity_blocked() -> RawInput:
    """Highly saline soil — should trigger amendment-or-halophyte path."""
    return RawInput(
        target_crop="tomato",
        latitude=31.10,
        longitude=31.30,
        area_feddan=2.0,
        water_source=WaterSource.GROUNDWATER,
        soil_type="sandy",
        budget_egp=8000,
        start_date=date(2026, 5, 1),
        harvest_horizon_days=150,
        language="ar",
        ph=8.4,
        salinity_ds_m=5.5,
    )
