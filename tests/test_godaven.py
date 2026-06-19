import unittest

from godaven_minyan_finder.formatting import render_text
from godaven_minyan_finder.godaven import normalize_radius_results, options_from_detail, titleize
from godaven_minyan_finder.location import LocationError, location_from_provider_payload, resolve_location
from godaven_minyan_finder.models import MinyanOption


class GoDavenTests(unittest.TestCase):
    def test_titleize_known_tefillah(self):
        self.assertEqual(titleize("shachris"), "Shacharis")
        self.assertEqual(titleize("mariv"), "Maariv")
        self.assertEqual(titleize("mincha"), "Mincha")

    def test_normalize_radius_result(self):
        payload = {
            "shuls": [
                {
                    "id": 1,
                    "name": "orach chaim",
                    "formatted_address": "1459 Lexington Ave",
                    "distance": 0.42,
                    "location_status": "unconfirmed",
                    "nextMinyan": {"type": "Shacharis", "time": "07:00:00"},
                }
            ]
        }
        option = normalize_radius_results(payload)[0]
        self.assertEqual(option.shul_name, "Orach Chaim")
        self.assertEqual(option.time, "7:00 AM")
        self.assertIn("location unconfirmed", option.caveats)

    def test_parse_lat_lng_query(self):
        loc = resolve_location("40.1,-73.9", geocode=False)
        self.assertEqual(loc.latitude, 40.1)
        self.assertEqual(loc.longitude, -73.9)
        self.assertEqual(loc.source, "explicit_lat_lng")

    def test_provider_payload_with_coordinates(self):
        loc = location_from_provider_payload(
            {
                "coordinate": {"latitude": 40.2, "longitude": -73.8},
                "location_label": "near me",
                "source": "test_provider",
                "limitations": ["approximate"],
            }
        )
        self.assertEqual(loc.latitude, 40.2)
        self.assertEqual(loc.longitude, -73.8)
        self.assertEqual(loc.label, "near me")
        self.assertEqual(loc.source, "test_provider")
        self.assertIn("approximate", loc.caveats)

    def test_provider_payload_adds_findmy_accuracy_and_freshness_caveats(self):
        loc = location_from_provider_payload(
            {
                "coordinate": {"latitude": 40.2, "longitude": -73.8, "accuracy_meters": 8.4},
                "entity_name": "Clarks iPhone",
                "requester_device_alias": "phone",
                "freshness_text": "2026-06-19T21:04:56Z",
                "source": "findmy_cache_devices",
            }
        )
        self.assertEqual(loc.label, "Clarks iPhone")
        self.assertIn("Current location came from Find My device: Clarks iPhone.", loc.caveats)
        self.assertTrue(any("updated about" in caveat for caveat in loc.caveats))
        self.assertIn("Find My reported location accuracy about 8 meters.", loc.caveats)

    def test_provider_payload_label_requires_geocode(self):
        with self.assertRaises(LocationError):
            location_from_provider_payload({"label": "Upper East Side"}, geocode=False)

    def test_render_text_promotes_location_assumption(self):
        loc = location_from_provider_payload(
            {
                "coordinate": {"latitude": 40.2, "longitude": -73.8, "accuracy_meters": 8.4},
                "entity_name": "Clarks iPhone",
                "freshness_text": "2026-06-19T21:04:56Z",
                "source": "findmy_cache_devices",
            }
        )
        option = MinyanOption(
            shul_id=1,
            shul_name="Test Shul",
            address="1 Main St",
            distance_miles=0.2,
            tefillah="Shacharis",
            time="7:00 AM",
            location_status="confirmed",
            source="test",
        )
        text = render_text(loc, [option])
        self.assertIn("I’m using Clarks iPhone from Find My as your location", text)
        self.assertIn("accuracy about 8 meters", text)
        self.assertNotIn("Parsed from encrypted local Find My cache", text)

    def test_detail_rows_exclude_special_day_only_by_default(self):
        base = MinyanOption(
            shul_id=1,
            shul_name="Test Shul",
            address="1 Main St",
            distance_miles=0.2,
            tefillah="Mincha",
            time="1:00 PM",
            location_status="confirmed",
            source="test",
        )
        detail = {
            "groupedByDayMinyanim": {
                "wed": {
                    "mincha": [
                        {"displayTime": "13:00:00", "special_days_only": True},
                        {"displayTime": "18:00:00"},
                    ]
                }
            }
        }
        options = options_from_detail(base, detail, tefillah="mincha", target_day="wed")
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0].time, "6:00 PM")


if __name__ == "__main__":
    unittest.main()
