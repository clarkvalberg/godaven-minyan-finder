import json
from dataclasses import asdict
import math
import re
from typing import Iterable, List, Optional

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
    lines = [f"*Location:* {assumption}", "", "*Next minyanim:*"]
    for option in rows:
        pieces = [_format_when(option), f"*{option.shul_name}*"]
        route = _route_estimate(option.distance_miles)
        if route:
            pieces.append(route)
        pieces.append(_address_link(option.address))
        phone = _phone_link(_phone_from_option(option))
        if phone:
            pieces.append(phone)
        caveat = f" ({'; '.join(option.caveats[:2])})" if option.caveats else ""
        lines.append("- " + " — ".join(pieces) + caveat)
    caveats = default_caveats(location, rows)
    if caveats:
        lines.append("Notes: " + " ".join(compact_caveats(caveats)))
    lines.append("_W = walk, D = drive._")
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
    freshness = _find_phrase(location.caveats, r"(?:Find My location|OpenClaw app location|Location) was updated (just now)\.")
    if not freshness:
        freshness = _find_phrase(location.caveats, r"(?:Find My location|OpenClaw app location|Location) was updated about ([^.]+)\.")
    accuracy = _find_phrase(location.caveats, r"(?:Find My reported location accuracy|OpenClaw app reported location accuracy|Location provider reported accuracy) about ([^.]+)\.")
    if location.source.startswith("openclaw_"):
        parts = [f"I’m using {device} from the OpenClaw app as your location"]
        if freshness:
            parts.append("updated just now" if freshness == "just now" else f"updated about {freshness}")
        if accuracy:
            parts.append(f"accuracy about {accuracy}")
        return "; ".join(parts) + "."
    if location.source.startswith("findmy_"):
        if location.label and location.label != device:
            parts = [f"{location.label}"]
            parts.append(f"{device} Find My")
        else:
            parts = [f"I’m using {device} from Find My as your location"]
        if freshness:
            if freshness == "just now":
                parts.append("updated just now")
            else:
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
        "Current location came from OpenClaw app:",
        "Find My location was updated",
        "OpenClaw app location was updated",
        "Find My reported location accuracy",
        "OpenClaw app reported location accuracy",
        "No requester device metadata was available",
    )
    return [caveat for caveat in caveats if not caveat.startswith(hidden_prefixes)]


def _format_when(option: MinyanOption) -> str:
    pieces = []
    if option.time:
        pieces.append(f"*{option.time}*")
    if option.tefillah:
        pieces.append(f"_{option.tefillah}_")
    return " ".join(pieces) if pieces else "_time not listed_"


def _route_estimate(distance_miles: Optional[float]) -> str:
    if distance_miles is None:
        return ""
    walk_minutes = max(1, int(math.ceil(distance_miles * 20)))
    drive_minutes = max(2, int(math.ceil(distance_miles * 8)))
    return f"*W* {walk_minutes}m / *D* {drive_minutes}m"


def _address_link(address: str) -> str:
    if not address:
        return ""
    return address


def _phone_from_option(option: MinyanOption) -> Optional[str]:
    phone = option.raw.get("phone") if option.raw else None
    if not phone:
        return None
    return str(phone)


def _phone_link(phone: Optional[str]) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        tel = f"+1{digits}"
        label = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    elif len(digits) == 11 and digits.startswith("1"):
        tel = f"+{digits}"
        label = f"{digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    else:
        tel = digits or phone
        label = phone
    return label


def _find_device(caveats: List[str]) -> Optional[str]:
    phrase = _find_phrase(caveats, r"Current location came from Find My device: ([^.]+)\.")
    if phrase:
        return phrase
    phrase = _find_phrase(caveats, r"Current location came from OpenClaw app: ([^.]+)\.")
    return phrase


def _find_phrase(caveats: List[str], pattern: str) -> Optional[str]:
    for caveat in caveats:
        match = re.search(pattern, caveat)
        if match:
            return match.group(1)
    return None
