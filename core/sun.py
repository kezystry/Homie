"""Sun — solar position for "is it actually dark?", stdlib only.

The lighting tile used a hardcoded 18:00–07:00 dark window, which is wrong by hours
at high latitude (second-review N4): at ~54°N civil dusk is ~22:00 in June and ~16:30
in December, so a constant cutoff lights the room in broad daylight half the year.

This computes sunrise/sunset (and any twilight depression) for a date + lat/long via
the standard sunrise equation — accurate to about a minute, which is far better than a
constant. No dependencies; pure functions of (epoch seconds, lat, lon). Time is in
absolute epoch seconds throughout, so the result is independent of the host timezone.
"""
from __future__ import annotations

import math

_DEG = math.pi / 180.0
_OBLIQUITY = 23.4397          # Earth's axial tilt, degrees
_J2000 = 2451545.0            # Julian date of 2000-01-01 12:00 TT
_GEOM = -0.833                # standard sunrise/sunset: sun centre at -0.833° (refraction + radius)
CIVIL = -6.0                  # civil twilight — a sensible "dark enough to want lights" threshold

POLAR_NIGHT = "polar_night"   # the sun never reaches the threshold this day (always dark)
POLAR_DAY = "polar_day"       # the sun never drops to the threshold this day (always light)


def _to_julian(ts: float) -> float:
    return ts / 86400.0 + 2440587.5


def _from_julian(j: float) -> float:
    return (j - 2440587.5) * 86400.0


def sun_events(ts: float, lat: float, lon: float, *, depression: float = _GEOM):
    """Return (sunrise_ts, sunset_ts) in epoch seconds for the solar day containing
    `ts`, or `POLAR_NIGHT` / `POLAR_DAY` when the sun never crosses `depression`
    (degrees below the horizon; 0 ≈ sunset, -6 = civil twilight). lat/lon in degrees."""
    jd = _to_julian(ts)
    n = round(jd - _J2000 + 0.0008)
    j_star = n - lon / 360.0
    M = (357.5291 + 0.98560028 * j_star) % 360.0       # solar mean anomaly
    Mr = M * _DEG
    C = 1.9148 * math.sin(Mr) + 0.0200 * math.sin(2 * Mr) + 0.0003 * math.sin(3 * Mr)
    lam = (M + C + 180.0 + 102.9372) % 360.0            # ecliptic longitude
    lamr = lam * _DEG
    j_transit = _J2000 + j_star + 0.0053 * math.sin(Mr) - 0.0069 * math.sin(2 * lamr)
    sin_delta = math.sin(lamr) * math.sin(_OBLIQUITY * _DEG)
    cos_delta = math.cos(math.asin(sin_delta))
    latr = lat * _DEG
    cos_w = (math.sin(depression * _DEG) - math.sin(latr) * sin_delta) / (math.cos(latr) * cos_delta)
    if cos_w > 1.0:
        return POLAR_NIGHT      # sun stays below the threshold all day
    if cos_w < -1.0:
        return POLAR_DAY        # sun stays above the threshold all day
    w0 = math.degrees(math.acos(cos_w))
    j_rise = j_transit - w0 / 360.0
    j_set = j_transit + w0 / 360.0
    return _from_julian(j_rise), _from_julian(j_set)


def is_dark(ts: float, lat: float, lon: float, *, depression: float = CIVIL) -> bool:
    """True if, at absolute time `ts`, the sun is below `depression` at (lat, lon) —
    i.e. it's dark enough to want lights. Defaults to civil twilight."""
    res = sun_events(ts, lat, lon, depression=depression)
    if res == POLAR_NIGHT:
        return True
    if res == POLAR_DAY:
        return False
    rise, set_ = res
    return not (rise <= ts <= set_)
