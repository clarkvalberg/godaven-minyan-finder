import json
from dataclasses import asdict
from typing import Iterable, List

from .models import Location, MinyanOption


def render_json(location: Location, options: Iterable[MinyanOption]) -> str:
    rows = list(options)
    return json.dumps(
        {
            "location": asdict(location),
            "results": [asdict(option) for option in rows],
            "caveats": default_caveats(location, rows),
        },
        indent=2,
        sort_keys=True,
    )


def render_text(location: Location, options: Iterable[MinyanOption], *, limit: int = 5) -> str:
    rows = list(options)[:limit]
    if not rows:
        return f"No nearby minyanim found near {location.label}."
    lines = [f"Nearby minyanim near {location.label}:"]
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
        lines.append("Caveat: " + " ".join(caveats))
    return "\n".join(lines)


def default_caveats(location: Location, options: List[MinyanOption]) -> List[str]:
    caveats = list(location.caveats)
    if any(option.location_status and option.location_status != "confirmed" for option in options):
        caveats.append("Some GoDaven locations are unconfirmed.")
    if any(option.time is None for option in options):
        caveats.append("Some results did not include an upcoming time.")
    caveats.append("Confirm with the shul when timing is critical or a special-day schedule may apply.")
    return caveats
