"""Governorate centroid lookup (rough lat/lon) for crop advisor seeding."""

GOVERNORATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "Sharqia":  (30.7327, 31.7195),
    "Minya":    (28.1099, 30.7503),
    "Beheira":  (30.8481, 30.3436),
    "Fayoum":   (29.3084, 30.8428),
    "Aswan":    (24.0889, 32.8998),
    "Cairo":    (30.0444, 31.2357),
    "Giza":     (29.9870, 31.2118),
    "Alexandria": (31.2001, 29.9187),
    "Qena":     (26.1551, 32.7160),
    "Sohag":    (26.5569, 31.6948),
}

DEFAULT_CENTROID = (30.0444, 31.2357)


def centroid(governorate: str) -> tuple[float, float]:
    return GOVERNORATE_CENTROIDS.get(governorate, DEFAULT_CENTROID)
