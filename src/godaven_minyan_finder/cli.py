import argparse
import sys
from datetime import datetime

from .formatting import render_json, render_text
from .godaven import GoDavenClient, best_options_with_details, normalize_radius_results
from .location import LocationError, resolve_location


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find nearby upcoming minyanim with GoDaven.")
    parser.add_argument("query", nargs="?", help="Address, venue, city, zip, or 'lat,lng'.")
    parser.add_argument("--lat", type=float, help="Latitude.")
    parser.add_argument("--lng", type=float, help="Longitude.")
    parser.add_argument("--near-me", action="store_true", help="Use a configured local location provider command.")
    parser.add_argument(
        "--location-provider-cmd",
        default="",
        help="Command that prints current-location JSON. Defaults to GODAVEN_LOCATION_PROVIDER_CMD.",
    )
    parser.add_argument("--distance", type=float, default=3, help="Search radius in miles. Default: 3.")
    parser.add_argument("--limit", type=int, default=5, help="Number of results. Default: 5.")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds. Default: 15.")
    parser.add_argument("--tefillah", default="", help="Filter tefillah, e.g. shachris, mincha, mariv.")
    parser.add_argument("--nusach", default="", help="GoDaven nusach filter.")
    parser.add_argument("--day", default="", help="GoDaven day filter.")
    parser.add_argument("--date", default="", help="User date passed to GoDaven. Optional.")
    parser.add_argument("--time", default="", help="Current/planning time passed to GoDaven. Optional.")
    parser.add_argument("--details", action="store_true", help="Fetch per-shul detail schedules for top radius results.")
    parser.add_argument(
        "--include-special-day-only",
        action="store_true",
        help="When using --details, include rows marked special-day only.",
    )
    parser.add_argument("--no-geocode", action="store_true", help="Disable external address geocoding.")
    parser.add_argument("--json", action="store_true", help="Return JSON.")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        location = resolve_location(
            args.query,
            lat=args.lat,
            lng=args.lng,
            near_me=args.near_me,
            geocode=not args.no_geocode,
            location_provider_cmd=args.location_provider_cmd or None,
        )
        client = GoDavenClient(timeout=args.timeout)
        payload = client.radius_search(
            lat=location.latitude,
            lng=location.longitude,
            distance=args.distance,
            nusach=args.nusach,
            tefillah=args.tefillah,
            day=args.day,
            current_time=args.time,
            todays_day=args.day,
            users_date=args.date,
        )
        detail_candidates = min(max(args.limit + 2, args.limit), 8)
        options = normalize_radius_results(payload, limit=detail_candidates if args.details else args.limit)
        if args.details:
            options = best_options_with_details(
                client,
                options,
                tefillah=args.tefillah,
                target_day=args.day or _today_key(),
                limit=args.limit,
                include_special_day_only=args.include_special_day_only,
            )
        else:
            options = options[: args.limit]
    except LocationError as exc:
        print(f"Location error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"GoDaven minyan finder failed: {exc}", file=sys.stderr)
        return 1

    print(render_json(location, options) if args.json else render_text(location, options, limit=args.limit))
    return 0


def _today_key() -> str:
    return ["mon", "tues", "wed", "thurs", "fri", "sat", "sun"][datetime.now().weekday()]


if __name__ == "__main__":
    raise SystemExit(main())
