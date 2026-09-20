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


class TelemetryTests(unittest.TestCase):
    def test_human_helpers(self):
        self.assertEqual(zte.human_bytes("1073741824"), "1.0 GiB")
        self.assertEqual(zte.human_duration("3661"), "1h 01m 01s")
        self.assertEqual(zte.human_rate("2048"), "2.0 KiB/s")

    def test_support_bundle_contains_only_safe_metadata(self):
        class Dummy(zte.ZTECPE):
            def __init__(self):
                pass

            def device_info(self):
                return {
                    "model": "MC_TEST",
                    "hardware_version": "HW1",
                    "firmware_version": "FW1",
                    "web_version": "WEB1",
                    "api_adapter": "legacy-goform-ld",
                }

            def capabilities(self):
                return {
                    "radio.lte": {
                        "state": "available",
                        "fields_present": ["lte_rsrp"],
                        "fields_nonempty": ["lte_rsrp"],
                    }
                }

        bundle = Dummy().support_bundle()
        payload_text = __import__("json").dumps({"app": bundle["app"], "device": bundle["device"], "capabilities": bundle["capabilities"]}).lower()
        self.assertFalse(bundle["privacy"]["contains_password"])
        self.assertFalse(bundle["privacy"]["contains_cookies"])
        self.assertFalse(bundle["privacy"]["contains_ip_addresses"])
        self.assertFalse(bundle["privacy"]["contains_mac_addresses"])
        self.assertFalse(bundle["privacy"]["contains_cell_ids"])
        self.assertNotIn("password", payload_text)
        self.assertNotIn("cookie", payload_text)
        self.assertNotIn("cell_id", payload_text)
        self.assertNotIn("wan_ipaddr", payload_text)
        self.assertNotIn("aa:bb:cc", payload_text)
