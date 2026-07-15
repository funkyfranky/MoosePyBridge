"""Typed DCS/MOOSE Bridge time information."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


SECONDS_PER_DAY = 86_400.0


@dataclass(slots=True, frozen=True)
class DcsTime:
    """Three synchronized time values reported by DCS.

    ``mission_time`` comes from ``timer.getTime()``, while ``dcs_time`` comes
    from ``timer.getAbsTime()`` and therefore contains the simulated time of
    day plus an optional day offset.
    """

    mission_time: float | None = None
    dcs_time: float | None = None
    wall_time: str | None = None
    sequence: int | None = None

    @classmethod
    def from_message(cls, message: dict[str, Any]) -> "DcsTime":
        """Create a clock value from a DCS protocol message or ACK."""

        result = message.get("result") if isinstance(message.get("result"), dict) else {}
        return cls(
            mission_time=_optional_float(message.get("mission_time", result.get("mission_time"))),
            dcs_time=_optional_float(message.get("dcs_time", result.get("dcs_time"))),
            wall_time=_optional_str(message.get("wall_time", result.get("wall_time"))),
            sequence=_optional_int(message.get("sequence")),
        )

    @property
    def day_offset(self) -> int | None:
        """Return the zero-based DCS day offset."""

        if self.dcs_time is None:
            return None
        return math.floor(self.dcs_time / SECONDS_PER_DAY)

    @property
    def seconds_of_day(self) -> float | None:
        """Return DCS time within the current day in seconds."""

        if self.dcs_time is None:
            return None
        return self.dcs_time % SECONDS_PER_DAY

    @property
    def time_of_day(self) -> str | None:
        """Return the DCS time of day as ``HH:MM:SS.mmm``."""

        seconds = self.seconds_of_day
        if seconds is None:
            return None
        milliseconds_of_day = int(seconds * 1000)
        whole_seconds, milliseconds = divmod(milliseconds_of_day, 1000)
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

    @property
    def mission_elapsed(self) -> str | None:
        """Return mission elapsed time as ``HH:MM:SS.mmm``."""

        if self.mission_time is None:
            return None
        milliseconds_total = max(0, int(self.mission_time * 1000))
        whole_seconds, milliseconds = divmod(milliseconds_total, 1000)
        hours, remainder = divmod(whole_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly clock metadata."""

        return {
            key: value
            for key, value in {
                "mission_time": self.mission_time,
                "mission_elapsed": self.mission_elapsed,
                "dcs_time": self.dcs_time,
                "dcs_day_offset": self.day_offset,
                "dcs_time_of_day": self.time_of_day,
                "wall_time": self.wall_time,
                "sequence": self.sequence,
            }.items()
            if value is not None
        }


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
