import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("zte_cpe", ROOT / "zte_cpe.py")
zte = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zte)


class NormalizeTests(unittest.TestCase):
    def test_admin_url_adds_http(self):
        self.assertEqual(zte.normalize_admin_url("192.168.0.1"), "http://192.168.0.1")

    def test_hex_fields_match_web_ui_decimal(self):
        self.assertEqual(zte.hex_to_dec("7b"), "123")
        self.assertEqual(zte.hex_to_dec("1f4"), "500")
        self.assertEqual(zte.hex_to_dec("1a2b3c"), "1715004")

    def test_signal_ratings(self):
        self.assertEqual(zte.rating("lte_rsrp", "-75"), "excellent")
        self.assertEqual(zte.rating("lte_rsrp", "-95"), "fair")
        self.assertEqual(zte.rating("nr_sinr", "26.5"), "excellent")

    def test_english_is_default_language(self):
        rows = zte.normalize({"lte_rsrp": "-85"}, "en")["rows"]
        rsrp = next(row for row in rows if row["name"] == "LTE RSRP")
        self.assertEqual(rsrp["rating_text"], "Good")
        self.assertIn("reference-signal power", rsrp["explanation"])


class AdapterTests(unittest.TestCase):
    def test_legacy_adapter_name_is_stable(self):
        self.assertEqual(zte.LegacyGoformAdapter.name, "legacy-goform-ld")


if __name__ == "__main__":
    unittest.main()
