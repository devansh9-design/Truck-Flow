"""Time helpers shared by both services so ETA rounding can never drift between them."""

from datetime import UTC, datetime, timedelta


def round_to_hour(t: datetime) -> datetime:
    """Nearest whole hour (spec D7); exactly :30:00 rounds up."""
    floor = t.replace(minute=0, second=0, microsecond=0)
    return floor + timedelta(hours=1) if t - floor >= timedelta(minutes=30) else floor


def iso_z(t: datetime) -> str:
    """UTC ISO 8601 with a 'Z' suffix, whole seconds."""
    return t.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
