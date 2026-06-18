import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import MinyanOption


BASE_URL = "https://www.godaven.com"
APP_ID_RE = re.compile(r'"app-id":"www\.godaven\.com"===window\.location\.host\?"([^"]+)"')


class GoDavenError(RuntimeError):
    pass


def discover_app_id(timeout: int = 20) -> str:
    override = os.environ.get("GODAVEN_APP_ID")
    if override:
        return override

    html = _http_text(f"{BASE_URL}/", timeout=timeout)
    match = re.search(r'src="(/static/js/main\.[^"]+\.js)"', html)
    if not match:
        raise GoDavenError("Could not locate GoDaven web app bundle.")
    bundle = _http_text(f"{BASE_URL}{match.group(1)}", timeout=timeout)
    app_id = APP_ID_RE.search(bundle)
    if not app_id:
        raise GoDavenError("Could not discover GoDaven app header.")
    return app_id.group(1)


class GoDavenClient:
    def __init__(self, app_id: Optional[str] = None, timeout: int = 25, retries: int = 1):
        self.timeout = timeout
        self.retries = retries
        self.app_id = app_id or discover_app_id(timeout=timeout)

    def radius_search(
        self,
        *,
        lat: float,
        lng: float,
        distance: float = 3,
        page: int = 1,
        nusach: str = "",
        tefillah: str = "",
        day: str = "",
        current_time: str = "",
        todays_day: str = "",
        users_date: str = "",
    ) -> Dict[str, Any]:
        query = urlencode(
            {
                "lat": f"{lat:.7f}",
                "lng": f"{lng:.7f}",
                "distance": distance,
                "pagenumber": page,
                "nusach": nusach,
                "tefillah": tefillah,
                "day": day,
                "current_time": current_time,
                "todays_day": todays_day,
                "users_date": users_date,
            }
        )
        return self._get_json(f"/api/V2/shuls/radius-search?{query}")

    def shul_details(self, shul_id: int) -> Dict[str, Any]:
        return self._get_json(f"/api/V2/shuls/{shul_id}/details")

    def shul_minyanim(self, shul_id: int) -> Dict[str, Any]:
        return self._get_json(f"/api/V2/shul/{shul_id}/minyanim")

    def _get_json(self, path: str) -> Dict[str, Any]:
        url = f"{BASE_URL}{path}"
        req = Request(
            url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "app-id": self.app_id,
                "User-Agent": "godaven-minyan-finder/0.1",
            },
        )
        payload = None
        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
                time.sleep(0.5 * (attempt + 1))
        if payload is None:
            raise GoDavenError(f"GoDaven request failed: {last_error}")
        if isinstance(payload, dict) and payload.get("code") and payload.get("message"):
            raise GoDavenError(f"GoDaven returned {payload.get('code')}: {payload.get('message')}")
        return payload


def normalize_radius_results(payload: Dict[str, Any], limit: int = 5) -> List[MinyanOption]:
    shuls = payload.get("shuls") or []
    options = [option_from_radius_shul(shul) for shul in shuls]
    options.sort(key=_sort_key)
    return options[:limit]


def option_from_radius_shul(shul: Dict[str, Any]) -> MinyanOption:
    next_minyan = shul.get("nextMinyan") or {}
    caveats: List[str] = []
    status = shul.get("location_status")
    if status and status != "confirmed":
        caveats.append(f"location {status}")
    if next_minyan.get("showRoshChodeshWarning"):
        caveats.append("Rosh Chodesh/special-day warning")
    if shul.get("temp_shul_confirmed"):
        caveats.append("temporary minyan")

    return MinyanOption(
        shul_id=int(shul["id"]),
        shul_name=titleize(shul.get("name") or "Unknown shul"),
        address=shul.get("formatted_address") or _join_address(shul),
        distance_miles=_safe_float(shul.get("distance")),
        tefillah=titleize(next_minyan.get("type")) if next_minyan.get("type") else None,
        time=_format_time(next_minyan.get("time")),
        location_status=status,
        source="godaven_radius",
        caveats=caveats,
        raw=shul,
    )


def best_options_with_details(
    client: GoDavenClient,
    options: Iterable[MinyanOption],
    *,
    tefillah: str = "",
    target_day: Optional[str] = None,
    limit: int = 5,
    include_special_day_only: bool = False,
) -> List[MinyanOption]:
    # Radius nextMinyan is generally enough for the concise default. Detail fetch
    # is best-effort, and never blocks returning useful radius options.
    enriched: List[MinyanOption] = []
    for option in options:
        try:
            detail = client.shul_details(option.shul_id)
            detail_options = options_from_detail(
                option,
                detail,
                tefillah=tefillah,
                target_day=target_day,
                include_special_day_only=include_special_day_only,
            )
            enriched.extend(detail_options or [option])
        except Exception:
            enriched.append(option)
    enriched.sort(key=_sort_key)
    return enriched[:limit]


def options_from_detail(
    base: MinyanOption,
    detail: Dict[str, Any],
    *,
    tefillah: str = "",
    target_day: Optional[str] = None,
    include_special_day_only: bool = False,
) -> List[MinyanOption]:
    grouped = detail.get("groupedByDayMinyanim") or {}
    days = [target_day] if target_day else _ordered_days_from_now()
    out: List[MinyanOption] = []
    for day in days:
        buckets = grouped.get(day) or {}
        for kind, rows in buckets.items():
            if tefillah and tefillah.lower() not in kind.lower():
                continue
            for row in rows or []:
                if row.get("special_days_only") and not include_special_day_only:
                    continue
                caveats = list(base.caveats)
                if row.get("special_days_only"):
                    caveats.append("special-day only")
                if row.get("special_days_included"):
                    caveats.append("special days included")
                if row.get("zman_type") or row.get("todays_dynamic_time"):
                    caveats.append("dynamic zman")
                if row.get("notes"):
                    caveats.append(str(row["notes"])[:80])
                out.append(
                    MinyanOption(
                        shul_id=base.shul_id,
                        shul_name=base.shul_name,
                        address=base.address,
                        distance_miles=base.distance_miles,
                        tefillah=titleize(kind),
                        time=_format_time(row.get("displayTime") or row.get("todays_time") or row.get("time_at")),
                        location_status=base.location_status,
                        source="godaven_details",
                        caveats=caveats,
                        raw=row,
                    )
                )
    return out


def _http_text(url: str, timeout: int) -> str:
    req = Request(url, headers={"User-Agent": "godaven-minyan-finder/0.1"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _safe_float(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _format_time(value: Any) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%-I:%M %p")
        except ValueError:
            pass
    return text


def titleize(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    replacements = {"shachris": "Shacharis", "mariv": "Maariv"}
    lower = value.strip().lower()
    if lower in replacements:
        return replacements[lower]
    return " ".join(part.capitalize() for part in lower.split())


def _join_address(shul: Dict[str, Any]) -> str:
    return ", ".join(str(shul.get(k)) for k in ("address", "city", "state") if shul.get(k))


def _sort_key(option: MinyanOption):
    return (
        1 if option.time is None else 0,
        _time_sort_minutes(option.time),
        option.distance_miles if option.distance_miles is not None else 999,
        option.shul_name,
    )


def _time_sort_minutes(value: Optional[str]) -> int:
    if not value:
        return 9999
    for fmt in ("%I:%M %p", "%H:%M:%S", "%H:%M"):
        try:
            parsed = datetime.strptime(value.strip(), fmt)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            pass
    return 9999


def _ordered_days_from_now() -> List[str]:
    today = datetime.now().weekday()
    order = ["mon", "tues", "wed", "thurs", "fri", "sat", "sun"]
    return order[today:] + order[:today]
