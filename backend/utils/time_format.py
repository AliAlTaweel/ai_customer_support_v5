"""Datetime formatting helpers."""

from datetime import UTC, datetime


def to_utc_iso_z(dt: datetime) -> str:
    """Format a datetime as a UTC ISO-8601 string with a trailing 'Z'.

    MongoDB (via Motor, tz_aware=False) returns naive datetimes that are
    implicitly UTC. Treat naive datetimes as UTC explicitly before
    formatting so the result is always Z-suffixed, regardless of whether
    the datetime read back is naive or already tz-aware.
    """
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.isoformat().replace("+00:00", "Z")
