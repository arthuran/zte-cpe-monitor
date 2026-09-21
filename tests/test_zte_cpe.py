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
        self.assertEqual(zte.rating("nr_sinr", "20"), "good")
        self.assertEqual(zte.rating("nr_sinr", "7"), "moderate")
        self.assertEqual(zte.rating("nr_sinr", "2"), "poor")
        self.assertEqual(zte.rating("nr_sinr", "-1"), "very_poor")

    def test_channel_numbers_decode_to_reference_frequency(self):
        lte = zte.lte_earfcn_info("1275")
        self.assertEqual(lte["band"], "B3")
        self.assertEqual(lte["frequency_mhz"], 1812.5)
        self.assertEqual(zte.nr_arfcn_frequency_mhz("529950"), 2649.75)

    def test_normalized_rows_include_reference_metadata(self):
        rows = zte.normalize(
            {
                "wan_active_band": "LTE BAND 3",
                "wan_active_channel": "1275",
                "nr5g_action_band": "n41",
                "nr5g_action_channel": "529950",
                "lte_rsrp": "-85",
                "lte_snr": "18",
                "Z5g_rsrp": "-58",
                "Z5g_SINR": "26.5",
            },
            "th",
        )["rows"]
        by_name = {row["name"]: row for row in rows}
        self.assertEqual(by_name["LTE RSRP"]["reference_key"], "rsrp")
        self.assertEqual(by_name["LTE EARFCN"]["detail"]["frequency_mhz"], 1812.5)
        self.assertEqual(by_name["5G NR-ARFCN"]["detail"]["frequency_mhz"], 2649.75)
        self.assertEqual(by_name["5G Band"]["detail"]["name"], "2500 MHz")

    def test_dashboard_contains_reference_ui(self):
        self.assertIn('id="refButton"', zte.DASHBOARD_HTML)
        self.assertIn('__REFERENCE_DATA__', zte.DASHBOARD_HTML)
        self.assertIn('id="refDialog"', zte.DASHBOARD_HTML)

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
