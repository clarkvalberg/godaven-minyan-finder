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

## Attribution And Gratitude

This project is an unofficial helper around [GoDaven](https://www.godaven.com/),
the Worldwide Orthodox Minyan Database. It exists because GoDaven does the hard
and communal work of collecting, maintaining, and presenting minyan information.
Any useful work in this repository should point attention and appreciation back
to the people and institutions who built and sustained the original service.

Please credit and support the original project:

- GoDaven site: https://www.godaven.com/
- Founder / maintainer: Yosi Fishkin, MD, as credited by GoDaven.
- Primary expansion / modernization backer: Klal Govoah, under the leadership
  of Ira Zlotowitz, as described by GoDaven's About page.
- Technology / rebuild partner: Bitbean, whose public case study describes its
  work modernizing GoDaven's mobile search, GPS-based nearby minyan lookup,
  dynamic rule/time-based schedule engine, crowdsourced updates, and temporary
  minyanim.

Sources:

- GoDaven About: https://www.godaven.com/about
- GoDaven homepage: https://www.godaven.com/
- Bitbean case study: https://www.bitbean.com/case-studies/godaven-bitbean-helps-mobile-website-fuel-prayer/

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

When `--near-me` is called from OpenClaw, prefer a requester-aware provider
that resolves the inbound device or channel metadata before querying Find My:

```bash
export GODAVEN_LOCATION_PROVIDER_CMD='findmy-request-location --json --provider cache --privacy machine'
```

The provider may include `requester_device_alias` and `entity_name`; the CLI
keeps those in the location caveats so the answer is clear about which Find My
device supplied the coordinates.

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
