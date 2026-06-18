# GoDaven Minyan Finder

Small deterministic CLI and agent helper for answering:

> What are the next nearby minyanim?

It accepts an explicit address, coordinates, or an opt-in local current-location
provider, queries GoDaven's current web app data surface, and returns a concise
ranked list: time, tefillah, shul, distance, address, and caveats.

## Status

Alpha. This is a thin adapter around GoDaven's observed public web app
endpoints. GoDaven does not appear to publish these endpoints as a formal
third-party API, so this package intentionally keeps the integration small and
replaceable. If this becomes a public product, get permission or move to an
official integration path.

## Install

From a checkout:

```bash
python3 -m pip install -e .
```

Or run directly:

```bash
bin/godaven-minyan --lat 40.779026 --lng -73.948226 --limit 5
```

## Examples

Explicit coordinates:

```bash
godaven-minyan --lat 40.779026 --lng -73.948226 --limit 5
```

Address lookup:

```bash
godaven-minyan "389 E 89th St, New York" --limit 5
```

Mincha only:

```bash
godaven-minyan "389 E 89th St, New York" --tefillah mincha --limit 5
```

Detailed schedule enrichment:

```bash
godaven-minyan "389 E 89th St, New York" --tefillah mincha --details
```

JSON for agents:

```bash
godaven-minyan "389 E 89th St, New York" --json
```

## Location Providers

`--near-me` is intentionally opt-in. Configure a command that prints JSON:

```bash
export GODAVEN_LOCATION_PROVIDER_CMD='my-location-provider --json'
godaven-minyan --near-me --limit 5
```

The provider may return coordinates:

```json
{
  "latitude": 40.779026,
  "longitude": -73.948226,
  "label": "Upper East Side",
  "source": "local_provider"
}
```

or:

```json
{
  "coordinate": {
    "latitude": 40.779026,
    "longitude": -73.948226
  },
  "location_label": "Upper East Side",
  "limitations": ["approximate"]
}
```

If the provider returns only `label` or `location_label`, the CLI geocodes that
label and marks the result as approximate.

## External Calls

- GoDaven web app endpoints are used for shul/minyan data.
- Address lookup and coarse label lookup use OpenStreetMap Nominatim.
- Set `GODAVEN_APP_ID` if you need to pin the app header; otherwise the CLI
  discovers the current value from GoDaven's public app bundle.

## Safety And Halachic Caveats

- Do not treat results as halachic advice.
- Confirm with the shul when timing is critical, stale, special-day based,
  dynamic-zman based, or location-unconfirmed.
- `--details` excludes rows marked special-day-only by default. Use
  `--include-special-day-only` only when that is intentionally what you want.
- Current location is sensitive. Do not send or log precise user location unless
  the user explicitly requested location-based results in a private context.
