import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Location


LAT_LNG_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
LOCATION_PROVIDER_ENV = "GODAVEN_LOCATION_PROVIDER_CMD"


class LocationError(RuntimeError):
    pass


def resolve_location(
    query: Optional[str],
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    near_me: bool = False,
    geocode: bool = True,
    location_provider_cmd: Optional[str] = None,
    max_stale_age_seconds: Optional[int] = None,
) -> Location:
    if lat is not None and lng is not None:
        return Location(latitude=float(lat), longitude=float(lng), label=f"{lat},{lng}", source="explicit_lat_lng")

    if query:
        match = LAT_LNG_RE.match(query)
        if match:
            return Location(
                latitude=float(match.group(1)),
                longitude=float(match.group(2)),
                label=query,
                source="explicit_lat_lng",
            )
        if geocode:
            return geocode_address(query)
        raise LocationError("Address geocoding is disabled.")

    if near_me:
        return resolve_near_me(
            geocode=geocode,
            location_provider_cmd=location_provider_cmd,
            max_stale_age_seconds=max_stale_age_seconds,
        )

    raise LocationError("Pass an address, lat/lng, or --near-me.")


def geocode_address(address: str) -> Location:
    params = urlencode({"format": "jsonv2", "limit": 1, "q": address})
    req = Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"User-Agent": "godaven-minyan-finder/0.1"},
    )
    with urlopen(req, timeout=25) as response:
        results = json.loads(response.read().decode("utf-8"))
    if not results:
        raise LocationError(f"Could not geocode: {address}")
    first = results[0]
    return Location(
        latitude=float(first["lat"]),
        longitude=float(first["lon"]),
        label=first.get("display_name") or address,
        source="nominatim",
        caveats=["address geocoded externally via OpenStreetMap Nominatim"],
    )


def reverse_geocode_coordinate(latitude: float, longitude: float) -> Location:
    params = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.7f}",
            "lon": f"{longitude:.7f}",
            "zoom": 18,
            "addressdetails": 1,
        }
    )
    req = Request(
        f"https://nominatim.openstreetmap.org/reverse?{params}",
        headers={"User-Agent": "godaven-minyan-finder/0.1"},
    )
    try:
        with urlopen(req, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise LocationError("Could not translate the current coordinate into an address.") from exc
    label = str(result.get("display_name") or "").strip() if isinstance(result, dict) else ""
    if not label:
        raise LocationError("Could not translate the current coordinate into an address.")
    return Location(
        latitude=latitude,
        longitude=longitude,
        label=label,
        source="nominatim_reverse",
        caveats=["current coordinate reverse-geocoded externally via OpenStreetMap Nominatim"],
    )


def resolve_near_me(
    *,
    geocode: bool = True,
    location_provider_cmd: Optional[str] = None,
    max_stale_age_seconds: Optional[int] = None,
) -> Location:
    command = location_provider_cmd or os.environ.get(LOCATION_PROVIDER_ENV)
    if not command:
        raise LocationError(
            f"--near-me needs a configured location provider command. Set {LOCATION_PROVIDER_ENV} "
            "to a command that prints JSON with coordinates or a location label."
        )

    try:
        completed = subprocess.run(
            shlex.split(command),
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=35,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise LocationError(f"Location provider failed: {detail or exc}") from exc
    except Exception as exc:
        raise LocationError(f"Location provider failed: {exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocationError("Location provider did not return JSON.") from exc
    return location_from_provider_payload(
        payload,
        geocode=geocode,
        max_stale_age_seconds=max_stale_age_seconds,
    )


def location_from_provider_payload(
    payload: Dict[str, Any],
    *,
    geocode: bool = True,
    max_stale_age_seconds: Optional[int] = None,
) -> Location:
    coord = payload.get("coordinate") or {}
    latitude = coord.get("latitude", payload.get("latitude"))
    longitude = coord.get("longitude", payload.get("longitude"))
    stale_caveat = ""
    if payload.get("usable") is False:
        provider = payload.get("provider") or "location provider"
        age = payload.get("age_seconds")
        stale_allowed = (
            latitude is not None
            and longitude is not None
            and isinstance(age, (int, float))
            and max_stale_age_seconds is not None
            and 0 <= float(age) <= max_stale_age_seconds
        )
        if stale_allowed:
            stale_caveat = (
                "Using a last-known location because the freshest available fix is "
                f"about {round(float(age) / 60)} minutes old."
            )
        else:
            age_detail = f" ({round(float(age) / 60)} minutes old)" if isinstance(age, (int, float)) else ""
            raise LocationError(f"{provider} returned a stale or unusable location{age_detail}.")
    if latitude is not None and longitude is not None:
        caveats = list(payload.get("limitations") or [])
        if stale_caveat:
            caveats.append(stale_caveat)
        requester = payload.get("entity_name") or payload.get("requester_device_alias")
        source = str(payload.get("source") or "")
        provider = str(payload.get("provider") or "")
        is_openclaw = source.startswith("openclaw_") or provider.startswith("openclaw")
        source_label = "OpenClaw app" if is_openclaw else "Find My device"
        if requester:
            caveats.append(f"Current location came from {source_label}: {requester}.")
        freshness = _freshness_caveat(payload, is_openclaw=is_openclaw)
        if freshness:
            caveats.append(freshness)
        accuracy = _accuracy_caveat(coord, is_openclaw=is_openclaw)
        if accuracy:
            caveats.append(accuracy)
        local_label = (
            payload.get("address")
            or payload.get("display_address")
            or payload.get("location_label")
            or payload.get("place_label")
            or payload.get("neighborhood")
            or payload.get("locality")
        )
        if not local_label and geocode:
            try:
                translated = reverse_geocode_coordinate(float(latitude), float(longitude))
            except LocationError as exc:
                caveats.append(str(exc))
            else:
                local_label = translated.label
                caveats.extend(translated.caveats)
        return Location(
            latitude=float(latitude),
            longitude=float(longitude),
            label=local_label
            or payload.get("label")
            or payload.get("entity_name")
            or payload.get("requester_device_alias")
            or "current location",
            source=payload.get("source") or "location_provider",
            caveats=caveats,
        )

    label = payload.get("location_label") or payload.get("label")
    if label:
        if not geocode:
            raise LocationError("Location provider returned only a text label and geocoding is disabled.")
        loc = geocode_address(label)
        return Location(
            latitude=loc.latitude,
            longitude=loc.longitude,
            label=label,
            source=(payload.get("source") or "location_provider") + "_label_geocoded",
            caveats=[
                "Location provider returned only a text label; coordinates are a geocoded approximation.",
                *loc.caveats,
                *(payload.get("limitations") or []),
            ],
        )

    raise LocationError("Location provider returned no usable coordinates or location label.")


def _accuracy_caveat(coord: Dict[str, Any], *, is_openclaw: bool = False) -> Optional[str]:
    accuracy = coord.get("accuracy_meters")
    if accuracy is None:
        return None
    try:
        meters = float(accuracy)
    except (TypeError, ValueError):
        return None
    if is_openclaw:
        return f"OpenClaw app reported location accuracy about {meters:.0f} meters."
    return f"Find My reported location accuracy about {meters:.0f} meters."


def _freshness_caveat(payload: Dict[str, Any], *, is_openclaw: bool = False) -> Optional[str]:
    freshness_text = payload.get("freshness_text")
    if not freshness_text:
        return None
    prefix = "OpenClaw app location" if is_openclaw else "Find My location"
    try:
        observed = datetime.fromisoformat(str(freshness_text).replace("Z", "+00:00"))
    except ValueError:
        return f"{prefix} timestamp: {freshness_text}."
    age = datetime.now(timezone.utc) - observed.astimezone(timezone.utc)
    minutes = max(0, round(age.total_seconds() / 60))
    if minutes == 0:
        return f"{prefix} was updated just now."
    unit = "minute" if minutes == 1 else "minutes"
    return f"{prefix} was updated about {minutes} {unit} ago."
