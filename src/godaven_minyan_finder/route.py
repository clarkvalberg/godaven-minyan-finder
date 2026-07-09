import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .godaven import GoDavenClient, normalize_radius_results
from .location import Location, geocode_address
from .models import MinyanOption


OSRM_BASE_URL = "http://router.project-osrm.org"


@dataclass(frozen=True)
class RouteMinyanOption:
    option: MinyanOption
    origin_to_stop_minutes: Optional[float]
    stop_to_destination_minutes: Optional[float]
    direct_minutes: Optional[float]
    detour_minutes: Optional[float]
    arrival_time: Optional[str]
    minyan_time: Optional[str]
    minutes_early: Optional[float]
    feasible: bool
    route_distance_miles: Optional[float]
    score: float
    caveats: List[str]


def route_aware_options(
    *,
    origin: Location,
    destination_query: str,
    tefillah: str,
    current_time: Optional[datetime] = None,
    search_radius_miles: float = 2.5,
    max_samples: int = 16,
    limit: int = 5,
    buffer_minutes: int = 5,
    timeout: int = 20,
    client: Optional[GoDavenClient] = None,
) -> Dict[str, Any]:
    destination = geocode_address(destination_query)
    now = current_time or datetime.now().astimezone()
    route = osrm_route(
        origin.latitude,
        origin.longitude,
        destination.latitude,
        destination.longitude,
        timeout=timeout,
    )
    coords = route["coordinates"]
    samples = sample_coordinates(coords, max_samples=max_samples)
    direct_minutes = route["duration_seconds"] / 60

    godaven = client or GoDavenClient(timeout=timeout)
    candidates: Dict[int, MinyanOption] = {}
    current_time_text = now.strftime("%H:%M:%S")
    for lat, lng in samples:
        payload = godaven.radius_search(
            lat=lat,
            lng=lng,
            distance=search_radius_miles,
            tefillah=tefillah,
            current_time=current_time_text,
            todays_day=_today_key(now),
        )
        for option in normalize_radius_results(payload, limit=12):
            if option.time:
                existing = candidates.get(option.shul_id)
                if existing is None or _time_minutes(option.time) < _time_minutes(existing.time):
                    candidates[option.shul_id] = option

    ranked: List[RouteMinyanOption] = []
    for option in candidates.values():
        point = _option_point(option)
        caveats = list(option.caveats)
        if not point:
            caveats.append("no coordinates for route scoring")
            ranked.append(
                RouteMinyanOption(
                    option=option,
                    origin_to_stop_minutes=None,
                    stop_to_destination_minutes=None,
                    direct_minutes=direct_minutes,
                    detour_minutes=None,
                    arrival_time=None,
                    minyan_time=option.time,
                    minutes_early=None,
                    feasible=False,
                    route_distance_miles=None,
                    score=99999,
                    caveats=caveats,
                )
            )
            continue
        stop_lat, stop_lng = point
        try:
            leg1 = osrm_route(origin.latitude, origin.longitude, stop_lat, stop_lng, timeout=timeout)
            leg2 = osrm_route(stop_lat, stop_lng, destination.latitude, destination.longitude, timeout=timeout)
            origin_to_stop = leg1["duration_seconds"] / 60
            stop_to_dest = leg2["duration_seconds"] / 60
            via = origin_to_stop + stop_to_dest
            detour = via - direct_minutes
            route_distance_miles = (leg1["distance_meters"] + leg2["distance_meters"]) / 1609.344
        except Exception as exc:
            caveats.append(f"route scoring failed: {exc}")
            origin_to_stop = stop_to_dest = detour = route_distance_miles = None

        minyan_dt = _combine_time(now, option.time)
        arrival_dt = now + timedelta(minutes=origin_to_stop) if origin_to_stop is not None else None
        minutes_early = None
        feasible = False
        if minyan_dt and arrival_dt:
            minutes_early = (minyan_dt - arrival_dt).total_seconds() / 60
            feasible = minutes_early >= buffer_minutes
            if minutes_early < 0:
                caveats.append("arrival after listed minyan time")
            elif minutes_early < buffer_minutes:
                caveats.append(f"less than {buffer_minutes} minute buffer")
        score = _score_route_option(
            feasible=feasible,
            detour_minutes=detour,
            minutes_early=minutes_early,
            location_status=option.location_status,
            minyan_time=option.time,
        )
        ranked.append(
            RouteMinyanOption(
                option=option,
                origin_to_stop_minutes=origin_to_stop,
                stop_to_destination_minutes=stop_to_dest,
                direct_minutes=direct_minutes,
                detour_minutes=detour,
                arrival_time=_format_dt(arrival_dt),
                minyan_time=option.time,
                minutes_early=minutes_early,
                feasible=feasible,
                route_distance_miles=route_distance_miles,
                score=score,
                caveats=caveats,
            )
        )

    ranked.sort(key=lambda item: item.score)
    return {
        "origin": _location_json(origin),
        "destination": _location_json(destination),
        "route": {
            "direct_minutes": round(direct_minutes, 1),
            "direct_distance_miles": round(route["distance_meters"] / 1609.344, 1),
            "sample_count": len(samples),
            "search_radius_miles": search_radius_miles,
            "buffer_minutes": buffer_minutes,
            "routing_backend": "OSRM public demo server",
        },
        "generated_at": now.isoformat(),
        "results": [route_option_json(item) for item in ranked[:limit]],
        "caveats": [
            "Route-aware mode uses a public routing backend and GoDaven public web-app data.",
            "Traffic is approximate; verify timing when the margin is tight.",
            "Do not treat results as halachic advice.",
        ],
    }


def osrm_route(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    *,
    timeout: int = 20,
) -> Dict[str, Any]:
    coordinates = f"{origin_lng:.7f},{origin_lat:.7f};{dest_lng:.7f},{dest_lat:.7f}"
    params = urlencode({"overview": "full", "geometries": "geojson", "steps": "false"})
    url = f"{OSRM_BASE_URL}/route/v1/driving/{coordinates}?{params}"
    req = Request(url, headers={"User-Agent": "godaven-minyan-finder/route-aware"})
    with urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    routes = payload.get("routes") or []
    if not routes:
        raise RuntimeError("routing backend returned no route")
    route = routes[0]
    coords = route.get("geometry", {}).get("coordinates") or []
    return {
        "duration_seconds": float(route["duration"]),
        "distance_meters": float(route["distance"]),
        "coordinates": [(float(lat), float(lng)) for lng, lat in coords],
    }


def sample_coordinates(coords: List[Tuple[float, float]], *, max_samples: int) -> List[Tuple[float, float]]:
    if not coords:
        return []
    if len(coords) <= max_samples:
        return coords
    out = []
    for i in range(max_samples):
        idx = round(i * (len(coords) - 1) / (max_samples - 1))
        out.append(coords[idx])
    return dedupe_nearby(out)


def dedupe_nearby(coords: Iterable[Tuple[float, float]], *, min_miles: float = 0.75) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for coord in coords:
        if all(haversine_miles(coord, existing) >= min_miles for existing in out):
            out.append(coord)
    return out


def haversine_miles(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def route_option_json(item: RouteMinyanOption) -> Dict[str, Any]:
    return {
        "shul_id": item.option.shul_id,
        "shul_name": item.option.shul_name,
        "address": item.option.address,
        "tefillah": item.option.tefillah,
        "time": item.option.time,
        "feasible": item.feasible,
        "arrival_time": item.arrival_time,
        "minutes_early": _round(item.minutes_early),
        "origin_to_stop_minutes": _round(item.origin_to_stop_minutes),
        "stop_to_destination_minutes": _round(item.stop_to_destination_minutes),
        "direct_minutes": _round(item.direct_minutes),
        "detour_minutes": _round(item.detour_minutes),
        "route_distance_miles": _round(item.route_distance_miles),
        "location_status": item.option.location_status,
        "caveats": item.caveats,
        "raw": item.option.raw,
    }


def _location_json(location: Location) -> Dict[str, Any]:
    return {
        "label": location.label,
        "latitude": location.latitude,
        "longitude": location.longitude,
        "source": location.source,
        "caveats": location.caveats,
    }


def _option_point(option: MinyanOption) -> Optional[Tuple[float, float]]:
    coords = ((option.raw or {}).get("location_point") or {}).get("coordinates") or []
    if len(coords) >= 2:
        return float(coords[1]), float(coords[0])
    return None


def _combine_time(now: datetime, value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value, fmt)
            candidate = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
            if candidate < now - timedelta(hours=6):
                candidate += timedelta(days=1)
            return candidate
        except ValueError:
            pass
    return None


def _score_route_option(
    *,
    feasible: bool,
    detour_minutes: Optional[float],
    minutes_early: Optional[float],
    location_status: Optional[str],
    minyan_time: Optional[str],
) -> float:
    detour = detour_minutes if detour_minutes is not None else 999
    early = minutes_early if minutes_early is not None else -999
    score = detour
    if not feasible:
        score += 1000 + max(0, -early)
    if location_status and location_status != "confirmed":
        score += 5
    score += _time_minutes(minyan_time) / 10000
    return score


def _time_minutes(value: Optional[str]) -> int:
    if not value:
        return 9999
    for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            pass
    return 9999


def _today_key(now: datetime) -> str:
    return ["mon", "tues", "wed", "thurs", "fri", "sat", "sun"][now.weekday()]


def _format_dt(value: Optional[datetime]) -> Optional[str]:
    return value.strftime("%-I:%M %p") if value else None


def _round(value: Optional[float]) -> Optional[float]:
    return None if value is None else round(value, 1)
