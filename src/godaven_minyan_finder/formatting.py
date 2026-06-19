import json
from dataclasses import asdict
import re
from typing import Iterable, List

from .models import Location, MinyanOption


def render_json(location: Location, options: Iterable[MinyanOption]) -> str:
    rows = list(options)
    return json.dumps(
        {
            "location": asdict(location),
            "location_assumption": location_assumption(location),
            "results": [asdict(option) for option in rows],
            "caveats": default_caveats(location, rows),
        },
        indent=2,
        sort_keys=True,
    )


def render_text(location: Location, options: Iterable[MinyanOption], *, limit: int = 5) -> str:
    rows = list(options)[:limit]
    assumption = location_assumption(location)
    if not rows:
        return "\n".join([assumption, f"No nearby minyanim found near {location.label}."])
    lines = [f"Nearby minyanim near {location.label}:", assumption]
    for option in rows:
        pieces = []
        if option.time:
            pieces.append(option.time)
        if option.tefillah:
            pieces.append(option.tefillah)
        pieces.append(option.shul_name)
        if option.distance_miles is not None:
            pieces.append(f"{option.distance_miles:.1f} mi")
        pieces.append(option.address)
        caveat = f" ({'; '.join(option.caveats[:2])})" if option.caveats else ""
        lines.append("- " + " — ".join(pieces) + caveat)
    caveats = default_caveats(location, rows)
    if caveats:
        lines.append("Notes: " + " ".join(compact_caveats(caveats)))
    return "\n".join(lines)


def default_caveats(location: Location, options: List[MinyanOption]) -> List[str]:
    caveats = list(location.caveats)
    if any(option.location_status and option.location_status != "confirmed" for option in options):
        caveats.append("Some GoDaven locations are unconfirmed.")
    if any(option.time is None for option in options):
        caveats.append("Some results did not include an upcoming time.")
    caveats.append("Confirm with the shul when timing is critical or a special-day schedule may apply.")
    return caveats


def location_assumption(location: Location) -> str:
    device = _find_device(location.caveats) or location.label
    freshness = _find_phrase(location.caveats, r"Find My location was updated about ([^.]+)\.")
    accuracy = _find_phrase(location.caveats, r"Find My reported location accuracy about ([^.]+)\.")
    if location.source.startswith("findmy_"):
        parts = [f"I’m using {device} from Find My as your location"]
        if freshness:
            parts.append(f"updated about {freshness}")
        if accuracy:
            parts.append(f"accuracy about {accuracy}")
        return "; ".join(parts) + "."
    if location.source == "explicit_lat_lng":
        return f"Using the coordinates you gave me: {location.label}."
    if location.source == "nominatim":
        return f"Using geocoded location: {location.label}."
    return f"Using location: {location.label}."


def compact_caveats(caveats: List[str]) -> List[str]:
    hidden_prefixes = (
        "Parsed from encrypted local Find My cache.",
        "Current location came from Find My device:",
        "Find My location was updated",
        "Find My reported location accuracy",
        "No requester device metadata was available",
    )
    return [caveat for caveat in caveats if not caveat.startswith(hidden_prefixes)]


def _find_device(caveats: List[str]) -> str | None:
    phrase = _find_phrase(caveats, r"Current location came from Find My device: ([^.]+)\.")
    return phrase


def _find_phrase(caveats: List[str], pattern: str) -> str | None:
    for caveat in caveats:
        match = re.search(pattern, caveat)
        if match:
            return match.group(1)
    return None
