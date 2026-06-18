import json
import os
import re
import shlex
import subprocess
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
        return resolve_near_me(geocode=geocode, location_provider_cmd=location_provider_cmd)

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


def resolve_near_me(*, geocode: bool = True, location_provider_cmd: Optional[str] = None) -> Location:
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
    except Exception as exc:
        raise LocationError(f"Find My bridge failed: {exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LocationError("Location provider did not return JSON.") from exc
    return location_from_provider_payload(payload, geocode=geocode)


def location_from_provider_payload(payload: Dict[str, Any], *, geocode: bool = True) -> Location:
    coord = payload.get("coordinate") or {}
    latitude = coord.get("latitude", payload.get("latitude"))
    longitude = coord.get("longitude", payload.get("longitude"))
    if latitude is not None and longitude is not None:
        return Location(
            latitude=float(latitude),
            longitude=float(longitude),
            label=payload.get("location_label") or payload.get("label") or "current location",
            source=payload.get("source") or "location_provider",
            caveats=payload.get("limitations") or [],
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
