#!/usr/bin/env python3
"""On-demand CLI and temporary dashboard for ZTE CPE radio status."""

import argparse
import getpass
import hashlib
import http.cookiejar
import html
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.1"
BASE_URL = "http://192.168.0.1"
APP_NAME = "ZTE CPE Monitor"
COMMAND_NAME = "zte-cpe"
CREDENTIAL_SERVICE = "zte-cpe-monitor"
LEGACY_CREDENTIAL_SERVICE = "mc7010-cli"
CONFIG_DIR = os.path.expanduser("~/.config/zte-cpe-monitor")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LEGACY_CONFIG_FILE = os.path.expanduser("~/.config/mc7010/config.json")
DEVICE_INFO_FIELDS = [
    "model_name", "product_name", "device_name", "hardware_version",
    "wa_inner_version", "cr_version", "web_version", "network_type",
]

FIELDS = [
    "wan_active_channel", "wan_active_band",
    "lte_rssi", "lte_rsrp", "lte_snr", "lte_rsrq", "lte_pci", "cell_id",
    "nr5g_action_channel", "nr5g_action_band", "Z5g_rsrp", "Z5g_SINR",
    "nr5g_pci", "wan_lte_ca", "lte_multi_ca_scell_info",
    "network_type", "signalbar",
]

CAPABILITY_GROUPS = {
    "radio.lte": ["wan_active_channel", "wan_active_band", "lte_rsrp", "lte_rsrq", "lte_snr", "lte_pci"],
    "radio.nr5g": ["nr5g_action_channel", "nr5g_action_band", "Z5g_rsrp", "Z5g_SINR", "nr5g_pci"],
    "radio.ca": ["wan_lte_ca", "lte_multi_ca_scell_info"],
    "radio.ca_detail": [
        "lte_ca_pcell_arfcn", "lte_ca_pcell_band", "lte_ca_pcell_bandwidth",
        "lte_ca_scell_band", "lte_ca_scell_bandwidth", "lte_ca_scell_arfcn", "lte_ca_scell_info",
    ],
    "device.identity": ["model_name", "hardware_version", "wa_inner_version", "web_version"],
    "network.mode": ["network_type", "signalbar"],
    "network.connection": ["wan_connect_status", "ppp_status", "realtime_time"],
    "traffic.realtime": ["realtime_tx_bytes", "realtime_rx_bytes", "realtime_tx_thrpt", "realtime_rx_thrpt"],
    "traffic.monthly": ["monthly_tx_bytes", "monthly_rx_bytes", "monthly_time"],
    "clients.summary": [
        "wifi_access_sta_num", "wifi_chip1_ssid1_access_sta_num", "wifi_chip2_ssid1_access_sta_num",
        "wifi_chip1_ssid2_access_sta_num", "wifi_chip2_ssid2_access_sta_num",
    ],
}

TELEMETRY_FIELDS = [
    "wan_connect_status", "ppp_status", "realtime_time",
    "realtime_tx_bytes", "realtime_rx_bytes", "realtime_tx_thrpt", "realtime_rx_thrpt",
    "monthly_tx_bytes", "monthly_rx_bytes", "monthly_time",
]

SUPPORT_BUNDLE_SAFE_DEVICE_FIELDS = {
    "model", "hardware_version", "firmware_version", "web_version", "api_adapter"
}

LANGUAGES = ("en", "th")

EXPLANATIONS = {
    "en": {
        "Mode": "Current network mode; ENDC means 5G NSA using LTE as the anchor.",
        "Signal bars": "ZTE's simplified signal indicator on a 0–5 bar scale.",
        "LTE Band": "The LTE frequency band currently in use, such as B3.",
        "LTE EARFCN": "LTE channel number used to identify the carrier/frequency channel.",
        "LTE RSRP": "LTE reference-signal power. Values closer to 0 dBm indicate a stronger signal.",
        "LTE RSRQ": "LTE reference-signal quality. It reflects signal quality and can be affected by interference or cell load.",
        "LTE SINR": "Signal-to-interference-plus-noise ratio. Higher values are better.",
        "LTE RSSI": "Total received RF power, including wanted signal, interference, and noise; best used as a secondary indicator.",
        "LTE PCI": "Physical Cell ID of the LTE cell currently serving the modem.",
        "LTE Cell ID": "Identifier of the LTE cell. It may change when the modem moves to another cell.",
        "LTE CA": "Carrier Aggregation. Multiple LTE carriers can be combined to increase throughput.",
        "5G Band": "The 5G NR frequency band currently in use, such as n41.",
        "5G NR-ARFCN": "5G NR channel number used to identify the current radio channel.",
        "5G RSRP": "5G reference-signal power. Values closer to 0 dBm indicate a stronger signal.",
        "5G SINR": "5G signal-to-interference-plus-noise ratio. Higher values are better.",
        "5G PCI": "Physical Cell ID of the serving 5G NR cell.",
    },
    "th": {
        "Mode": "โหมดเครือข่ายปัจจุบัน; ENDC หมายถึง 5G NSA ที่ใช้ LTE เป็น anchor",
        "Signal bars": "ระดับสัญญาณแบบย่อของ ZTE ในช่วง 0–5 ขีด",
        "LTE Band": "ย่านความถี่ LTE ที่เชื่อมต่ออยู่ เช่น B3",
        "LTE EARFCN": "หมายเลขช่องสัญญาณ LTE ใช้ระบุ carrier/frequency channel",
        "LTE RSRP": "กำลังสัญญาณอ้างอิง LTE ค่ายิ่งใกล้ 0 dBm ยิ่งแรง",
        "LTE RSRQ": "คุณภาพสัญญาณอ้างอิง LTE ซึ่งได้รับผลจาก interference และ load ของ cell ได้",
        "LTE SINR": "อัตราส่วนสัญญาณต่อสัญญาณรบกวน ค่ายิ่งสูงยิ่งดี",
        "LTE RSSI": "พลังงาน RF รวมที่รับได้ รวมทั้งสัญญาณที่ต้องการ interference และ noise จึงเหมาะใช้เป็นค่าประกอบ",
        "LTE PCI": "Physical Cell ID ของเซลล์ LTE ที่กำลังให้บริการ modem",
        "LTE Cell ID": "รหัสเซลล์ LTE อาจเปลี่ยนเมื่อ modem ย้ายไปเกาะ cell อื่น",
        "LTE CA": "Carrier Aggregation การรวมหลาย LTE carriers เพื่อเพิ่ม throughput",
        "5G Band": "ย่านความถี่ 5G NR ที่เชื่อมต่ออยู่ เช่น n41",
        "5G NR-ARFCN": "หมายเลขช่องสัญญาณ 5G NR ที่กำลังใช้งาน",
        "5G RSRP": "กำลังสัญญาณอ้างอิง 5G ค่ายิ่งใกล้ 0 dBm ยิ่งแรง",
        "5G SINR": "อัตราส่วนสัญญาณ 5G ต่อสัญญาณรบกวน ค่ายิ่งสูงยิ่งดี",
        "5G PCI": "Physical Cell ID ของเซลล์ 5G NR ที่กำลังให้บริการ",
    },
}

RATING_TEXTS = {
    "en": {
        "excellent": "Excellent",
        "good": "Good",
        "moderate": "Moderate",
        "fair": "Fair",
        "poor": "Poor",
        "very_poor": "Very poor",
        "unknown": "No data",
    },
    "th": {
        "excellent": "ดีมาก",
        "good": "ดี",
        "moderate": "ปานกลาง",
        "fair": "พอใช้",
        "poor": "แย่",
        "very_poor": "แย่มาก",
        "unknown": "ไม่มีข้อมูล",
    },
}

SIGNAL_REFERENCE = {
    "rsrp": [
        {"rating": "excellent", "range": "≥ -80 dBm"},
        {"rating": "good", "range": "-90 to < -80 dBm"},
        {"rating": "fair", "range": "-100 to < -90 dBm"},
        {"rating": "poor", "range": "< -100 dBm"},
    ],
    "sinr": [
        {"rating": "excellent", "range": "> 20 dB"},
        {"rating": "good", "range": "13 to 20 dB"},
        {"rating": "moderate", "range": "5 to < 13 dB"},
        {"rating": "poor", "range": "0 to < 5 dB"},
        {"rating": "very_poor", "range": "< 0 dB"},
    ],
}

# Common sub-6 GHz bands documented across MC7010 variants. Exact supported bands
# vary by hardware revision and firmware. EARFCN parameters follow 3GPP TS 36.101.
LTE_BAND_REFERENCE = [
    {"band": "B1", "name": "2100 MHz", "duplex": "FDD", "uplink": "1920–1980", "downlink": "2110–2170", "earfcn": [0, 599], "fdl_low": 2110.0, "n_offs_dl": 0},
    {"band": "B3", "name": "1800 MHz", "duplex": "FDD", "uplink": "1710–1785", "downlink": "1805–1880", "earfcn": [1200, 1949], "fdl_low": 1805.0, "n_offs_dl": 1200},
    {"band": "B5", "name": "850 MHz", "duplex": "FDD", "uplink": "824–849", "downlink": "869–894", "earfcn": [2400, 2649], "fdl_low": 869.0, "n_offs_dl": 2400},
    {"band": "B7", "name": "2600 MHz", "duplex": "FDD", "uplink": "2500–2570", "downlink": "2620–2690", "earfcn": [2750, 3449], "fdl_low": 2620.0, "n_offs_dl": 2750},
    {"band": "B8", "name": "900 MHz", "duplex": "FDD", "uplink": "880–915", "downlink": "925–960", "earfcn": [3450, 3799], "fdl_low": 925.0, "n_offs_dl": 3450},
    {"band": "B20", "name": "800 MHz", "duplex": "FDD", "uplink": "832–862", "downlink": "791–821", "earfcn": [6150, 6449], "fdl_low": 791.0, "n_offs_dl": 6150},
    {"band": "B28", "name": "700 MHz", "duplex": "FDD", "uplink": "703–748", "downlink": "758–803", "earfcn": [9210, 9659], "fdl_low": 758.0, "n_offs_dl": 9210},
    {"band": "B34", "name": "2000 MHz", "duplex": "TDD", "uplink": "2010–2025", "downlink": "2010–2025", "earfcn": [36200, 36349], "fdl_low": 2010.0, "n_offs_dl": 36200},
    {"band": "B38", "name": "2600 MHz", "duplex": "TDD", "uplink": "2570–2620", "downlink": "2570–2620", "earfcn": [37750, 38249], "fdl_low": 2570.0, "n_offs_dl": 37750},
    {"band": "B39", "name": "1900 MHz", "duplex": "TDD", "uplink": "1880–1920", "downlink": "1880–1920", "earfcn": [38250, 38649], "fdl_low": 1880.0, "n_offs_dl": 38250},
    {"band": "B40", "name": "2300 MHz", "duplex": "TDD", "uplink": "2300–2400", "downlink": "2300–2400", "earfcn": [38650, 39649], "fdl_low": 2300.0, "n_offs_dl": 38650},
    {"band": "B41", "name": "2500 MHz", "duplex": "TDD", "uplink": "2496–2690", "downlink": "2496–2690", "earfcn": [39650, 41589], "fdl_low": 2496.0, "n_offs_dl": 39650},
]

NR_BAND_REFERENCE = [
    {"band": "n1", "name": "2100 MHz", "duplex": "FDD", "uplink": "1920–1980", "downlink": "2110–2170"},
    {"band": "n3", "name": "1800 MHz", "duplex": "FDD", "uplink": "1710–1785", "downlink": "1805–1880"},
    {"band": "n7", "name": "2600 MHz", "duplex": "FDD", "uplink": "2500–2570", "downlink": "2620–2690"},
    {"band": "n8", "name": "900 MHz", "duplex": "FDD", "uplink": "880–915", "downlink": "925–960"},
    {"band": "n20", "name": "800 MHz", "duplex": "FDD", "uplink": "832–862", "downlink": "791–821"},
    {"band": "n28", "name": "700 MHz", "duplex": "FDD", "uplink": "703–748", "downlink": "758–803"},
    {"band": "n38", "name": "2600 MHz", "duplex": "TDD", "uplink": "2570–2620", "downlink": "2570–2620"},
    {"band": "n40", "name": "2300 MHz", "duplex": "TDD", "uplink": "2300–2400", "downlink": "2300–2400"},
    {"band": "n41", "name": "2500 MHz", "duplex": "TDD", "uplink": "2496–2690", "downlink": "2496–2690"},
    {"band": "n77", "name": "3700 MHz", "duplex": "TDD", "uplink": "3300–4200", "downlink": "3300–4200"},
    {"band": "n78", "name": "3500 MHz", "duplex": "TDD", "uplink": "3300–3800", "downlink": "3300–3800"},
    {"band": "n79", "name": "4700 MHz", "duplex": "TDD", "uplink": "4400–5000", "downlink": "4400–5000"},
]

REFERENCE_DATA = {
    "signal": SIGNAL_REFERENCE,
    "lte_bands": [{k: v for k, v in row.items() if k not in {"fdl_low", "n_offs_dl"}} for row in LTE_BAND_REFERENCE],
    "nr_bands": NR_BAND_REFERENCE,
}

REFERENCE_KEYS = {
    "LTE RSRP": "rsrp",
    "5G RSRP": "rsrp",
    "LTE SINR": "sinr",
    "5G SINR": "sinr",
    "LTE Band": "lte_band",
    "LTE EARFCN": "lte_channel",
    "5G Band": "nr_band",
    "5G NR-ARFCN": "nr_channel",
}


class ZTECPEError(RuntimeError):
    pass


def run_security(args):
    return subprocess.run(
        ["security", *args], capture_output=True, text=True, check=False
    )


def credential_get():
    account = getpass.getuser()

    if sys.platform == "darwin":
        for service in (CREDENTIAL_SERVICE, LEGACY_CREDENTIAL_SERVICE):
            p = run_security(["find-generic-password", "-a", account, "-s", service, "-w"])
            if p.returncode == 0:
                return p.stdout.rstrip("\n")
        return None

    secret_tool = shutil.which("secret-tool")
    if secret_tool:
        p = subprocess.run(
            [secret_tool, "lookup", "application", CREDENTIAL_SERVICE, "account", account],
            capture_output=True,
            text=True,
            check=False,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout.rstrip("\n")

    return None


def credential_set(password):
    account = getpass.getuser()

    if sys.platform == "darwin":
        p = subprocess.run(
            [
                "security", "add-generic-password", "-U",
                "-a", account,
                "-s", CREDENTIAL_SERVICE,
                "-l", APP_NAME,
                "-w",
            ],
            input=password + "\n" + password + "\n",
            text=True,
            capture_output=True,
            check=False,
        )
        if p.returncode != 0:
            raise ZTECPEError("Failed to save password in macOS Keychain: " + p.stderr.strip())
        return "macOS Keychain"

    secret_tool = shutil.which("secret-tool")
    if secret_tool:
        p = subprocess.run(
            [
                secret_tool, "store",
                "--label", APP_NAME,
                "application", CREDENTIAL_SERVICE,
                "account", account,
            ],
            input=password,
            text=True,
            capture_output=True,
            check=False,
        )
        if p.returncode == 0:
            return "Secret Service"
        raise ZTECPEError("Failed to save password using Secret Service: " + p.stderr.strip())

    return None


def credential_delete():
    account = getpass.getuser()

    if sys.platform == "darwin":
        removed = False
        last = None
        for service in (CREDENTIAL_SERVICE, LEGACY_CREDENTIAL_SERVICE):
            p = run_security(["delete-generic-password", "-a", account, "-s", service])
            last = p
            if p.returncode == 0:
                removed = True
        if removed:
            return subprocess.CompletedProcess([], 0, "", "")
        return last or subprocess.CompletedProcess([], 1, "", "")

    secret_tool = shutil.which("secret-tool")
    if secret_tool:
        return subprocess.run(
            [secret_tool, "clear", "application", CREDENTIAL_SERVICE, "account", account],
            capture_output=True,
            text=True,
            check=False,
        )

    return subprocess.CompletedProcess([], 1, "", "No supported credential store found")


def normalize_admin_url(value):
    value = (value or "").strip()
    if not value:
        raise ZTECPEError("Admin URL ว่าง")
    if "://" not in value:
        value = "http://" + value
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ZTECPEError("Admin URL ต้องเป็น http://... หรือ https://...")
    if parsed.query or parsed.fragment:
        raise ZTECPEError("Admin URL ไม่ควรมี query หรือ fragment")
    path = parsed.path.rstrip("/")
    if path:
        raise ZTECPEError("Admin URL ต้องชี้ที่ root ของอุปกรณ์ เช่น http://192.168.0.1")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def config_load():
    for path in (CONFIG_FILE, LEGACY_CONFIG_FILE):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return {}


def config_save(admin_url=None, language=None):
    data = config_load()

    if admin_url is not None:
        data["admin_url"] = normalize_admin_url(admin_url)

    if language is not None:
        language = str(language).lower()
        if language not in LANGUAGES:
            raise ZTECPEError("Language must be 'en' or 'th'")
        data["language"] = language

    if data.get("language") not in LANGUAGES:
        data["language"] = "en"

    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    try:
        os.chmod(CONFIG_DIR, 0o700)
    except OSError:
        pass
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_FILE)
    return data


def saved_admin_url():
    value = config_load().get("admin_url")
    if not value:
        return None
    try:
        return normalize_admin_url(value)
    except ZTECPEError:
        return None


def saved_language():
    language = str(config_load().get("language", "en")).lower()
    return language if language in LANGUAGES else "en"


def prompt_admin_url(default=None, language="en"):
    default = default or BASE_URL
    prompt = "ZTE CPE admin URL" if language == "en" else "URL หน้าแอดมิน ZTE CPE"
    value = input(f"{prompt} [{default}]: ").strip()
    return normalize_admin_url(value or default)


def validate_credentials(admin_url, password):
    client = ZTECPE(password, base_url=admin_url)
    client.login()
    return client


def first_run_setup():
    language = saved_language()
    print("First-time ZTE CPE setup" if language == "en" else "ตั้งค่า ZTE CPE ครั้งแรก")
    admin_url = prompt_admin_url(BASE_URL, language)
    password = getpass.getpass("ZTE CPE password: ")
    if not password:
        raise ZTECPEError("No password entered" if language == "en" else "ไม่ได้ป้อนรหัสผ่าน")
    client = validate_credentials(admin_url, password)
    config_save(admin_url=admin_url)
    credential_set(password)
    if language == "en":
        print(f"✓ Saved Admin URL: {admin_url}")
        print("✓ Saved password in the secure credential store\n")
    else:
        print(f"✓ บันทึก Admin URL: {admin_url}")
        print("✓ บันทึกรหัสผ่านไว้ใน secure credential store แล้ว\n")
    return admin_url, password, client


def load_runtime_credentials():
    language = saved_language()
    admin_url = saved_admin_url()
    password = credential_get()
    if not admin_url:
        return first_run_setup()
    if not password:
        print(f"Admin URL: {admin_url}")
        password = getpass.getpass("ZTE CPE password: ")
        if not password:
            raise ZTECPEError("No password entered" if language == "en" else "ไม่ได้ป้อนรหัสผ่าน")
        client = validate_credentials(admin_url, password)
        credential_set(password)
        print(
            "✓ Saved password in the secure credential store\n"
            if language == "en"
            else "✓ บันทึกรหัสผ่านไว้ใน secure credential store แล้ว\n"
        )
        return admin_url, password, client
    return admin_url, password, ZTECPE(password, base_url=admin_url)


def sha256_upper(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


class LegacyGoformAdapter:
    name = "legacy-goform-ld"

    @staticmethod
    def login(client):
        ld = client._request(
            "/goform/goform_get_cmd_process",
            {"isTest": "false", "cmd": "LD", "multi_data": "1"},
        ).get("LD", "")
        if not ld:
            raise ZTECPEError("Unable to read the LD login challenge")
        signature = sha256_upper(sha256_upper(client.password) + ld)
        result = client._request(
            "/goform/goform_set_cmd_process",
            data={"isTest": "false", "goformId": "LOGIN", "password": signature},
        )
        if str(result.get("result")) != "0":
            raise ZTECPEError(f"Login failed (result={result.get('result')!r})")

    @staticmethod
    def get(client, fields):
        return client._request(
            "/goform/goform_get_cmd_process",
            {"isTest": "false", "multi_data": "1", "cmd": ",".join(fields)},
        )


ADAPTERS = (LegacyGoformAdapter,)


class ZTECPE:
    def __init__(self, password, base_url=BASE_URL, timeout=5, adapter=None):
        self.password = password
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.lock = threading.Lock()
        self.logged_in = False
        self.adapter = adapter or LegacyGoformAdapter

    def _request(self, path, params=None, data=None):
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Referer": self.base + "/",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": f"zte-cpe-monitor/{VERSION}",
            },
        )
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.URLError as e:
            raise ZTECPEError(f"ติดต่อ ZTE CPE ไม่ได้ที่ {self.base}: {e}") from e
        except json.JSONDecodeError as e:
            raise ZTECPEError("ZTE CPE ตอบกลับมาไม่ใช่ JSON") from e

    def login(self):
        with self.lock:
            self.adapter.login(self)
            self.logged_in = True

    def device_info(self):
        if not self.logged_in:
            self.login()
        raw = self.adapter.get(self, DEVICE_INFO_FIELDS)
        model = raw.get("model_name") or raw.get("product_name") or raw.get("device_name") or "Unknown ZTE CPE"
        return {
            "model": model,
            "hardware_version": raw.get("hardware_version") or "",
            "firmware_version": raw.get("wa_inner_version") or raw.get("cr_version") or "",
            "web_version": raw.get("web_version") or "",
            "api_adapter": self.adapter.name,
        }

    def capabilities(self):
        if not self.logged_in:
            self.login()
        all_fields = []
        for fields in CAPABILITY_GROUPS.values():
            for field in fields:
                if field not in all_fields:
                    all_fields.append(field)
        raw = self.adapter.get(self, all_fields)
        groups = {}
        for name, fields in CAPABILITY_GROUPS.items():
            present = [field for field in fields if field in raw]
            nonempty = [field for field in fields if raw.get(field) not in (None, "")]
            if nonempty:
                state = "available"
            elif present:
                state = "present-empty"
            else:
                state = "unavailable"
            groups[name] = {
                "state": state,
                "fields_present": present,
                "fields_nonempty": nonempty,
            }
        return groups

    def telemetry(self):
        if not self.logged_in:
            self.login()
        return self.adapter.get(self, TELEMETRY_FIELDS)

    def support_bundle(self):
        info = self.device_info()
        capabilities = self.capabilities()
        return {
            "schema_version": 1,
            "app": {"name": APP_NAME, "version": VERSION},
            "device": {key: info.get(key, "") for key in sorted(SUPPORT_BUNDLE_SAFE_DEVICE_FIELDS)},
            "capabilities": capabilities,
            "privacy": {
                "contains_password": False,
                "contains_cookies": False,
                "contains_ip_addresses": False,
                "contains_mac_addresses": False,
                "contains_cell_ids": False,
                "contains_radio_values": False,
                "contains_ssid_or_hostname": False,
            },
        }

    def raw_status(self):
        with self.lock:
            if not self.logged_in:
                # login() also takes the lock, so do it outside.
                pass
        if not self.logged_in:
            self.login()

        raw = self.adapter.get(self, FIELDS)
        meaningful = [raw.get("lte_rsrp"), raw.get("Z5g_rsrp"), raw.get("network_type")]
        if not any(v not in (None, "") for v in meaningful):
            self.logged_in = False
            self.login()
            raw = self.adapter.get(self, FIELDS)
        return raw


def human_bytes(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    for unit in units:
        if abs(number) < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return "—"


def human_duration(value):
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return "—"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    return f"{minutes}m {seconds:02d}s"


def human_rate(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    # ZTE legacy fields are reported in bytes per second on tested firmware.
    return human_bytes(number) + "/s"


def hex_to_dec(value):
    if value in (None, ""):
        return "—"
    try:
        return str(int(str(value), 16))
    except ValueError:
        return str(value)


def clean_band(value, prefix):
    if not value:
        return "—"
    v = str(value).strip()
    if prefix == "LTE":
        v = v.replace("LTE BAND ", "B").replace("LTE BAND", "B")
    return v


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rating(metric, value):
    x = num(value)
    if x is None:
        return "unknown"
    if metric in ("lte_rsrp", "nr_rsrp"):
        if x >= -80:
            return "excellent"
        if x >= -90:
            return "good"
        if x >= -100:
            return "fair"
        return "poor"
    if metric in ("lte_sinr", "nr_sinr"):
        if x > 20:
            return "excellent"
        if x >= 13:
            return "good"
        if x >= 5:
            return "moderate"
        if x >= 0:
            return "poor"
        return "very_poor"
    if metric == "lte_rsrq":
        if x >= -10:
            return "excellent"
        if x >= -15:
            return "good"
        if x >= -20:
            return "fair"
        return "poor"
    return "unknown"


def lte_earfcn_info(value):
    try:
        channel = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    for row in LTE_BAND_REFERENCE:
        first, last = row["earfcn"]
        if first <= channel <= last:
            frequency = row["fdl_low"] + 0.1 * (channel - row["n_offs_dl"])
            return {
                "band": row["band"],
                "frequency_mhz": round(frequency, 3),
                "direction": "downlink",
            }
    return None


def nr_arfcn_frequency_mhz(value):
    try:
        channel = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if 0 <= channel <= 599999:
        return round(channel * 0.005, 3)
    if 600000 <= channel <= 2016666:
        return round(3000.0 + (channel - 600000) * 0.015, 3)
    if 2016667 <= channel <= 3279165:
        return round(24250.08 + (channel - 2016667) * 0.06, 3)
    return None


def band_reference(kind, band):
    rows = LTE_BAND_REFERENCE if kind == "lte" else NR_BAND_REFERENCE
    normalized = str(band or "").strip().lower()
    for row in rows:
        if row["band"].lower() == normalized:
            return {k: v for k, v in row.items() if k not in {"fdl_low", "n_offs_dl"}}
    return None


def fmt(value, unit=""):
    if value in (None, ""):
        return "—"
    return f"{value}{(' ' + unit) if unit else ''}"


def normalize(raw, language="en"):
    language = language if language in LANGUAGES else "en"
    mode_raw = raw.get("network_type", "")
    mode = "5G NSA / ENDC" if mode_raw == "ENDC" else (mode_raw or "—")
    ca_raw = raw.get("wan_lte_ca") or raw.get("lte_multi_ca_scell_info")
    ca = "No" if not ca_raw else str(ca_raw)
    lte_band = clean_band(raw.get("wan_active_band"), "LTE")
    nr_band = clean_band(raw.get("nr5g_action_band"), "NR")
    lte_channel_info = lte_earfcn_info(raw.get("wan_active_channel"))
    nr_frequency = nr_arfcn_frequency_mhz(raw.get("nr5g_action_channel"))

    details = {
        "LTE Band": band_reference("lte", lte_band),
        "LTE EARFCN": lte_channel_info,
        "5G Band": band_reference("nr", nr_band),
        "5G NR-ARFCN": {
            "band": nr_band if nr_band != "—" else None,
            "frequency_mhz": nr_frequency,
            "direction": "reference",
        } if nr_frequency is not None else None,
    }

    rows = [
        ("Mode", mode, None),
        ("Signal bars", fmt(raw.get("signalbar"), "/5"), None),
        ("LTE Band", lte_band, None),
        ("LTE EARFCN", fmt(raw.get("wan_active_channel")), None),
        ("LTE RSRP", fmt(raw.get("lte_rsrp"), "dBm"), rating("lte_rsrp", raw.get("lte_rsrp"))),
        ("LTE RSRQ", fmt(raw.get("lte_rsrq"), "dB"), rating("lte_rsrq", raw.get("lte_rsrq"))),
        ("LTE SINR", fmt(raw.get("lte_snr"), "dB"), rating("lte_sinr", raw.get("lte_snr"))),
        ("LTE RSSI", fmt(raw.get("lte_rssi"), "dBm"), None),
        ("LTE PCI", hex_to_dec(raw.get("lte_pci")), None),
        ("LTE Cell ID", hex_to_dec(raw.get("cell_id")), None),
        ("LTE CA", ca, None),
        ("5G Band", nr_band, None),
        ("5G NR-ARFCN", fmt(raw.get("nr5g_action_channel")), None),
        ("5G RSRP", fmt(raw.get("Z5g_rsrp"), "dBm"), rating("nr_rsrp", raw.get("Z5g_rsrp"))),
        ("5G SINR", fmt(raw.get("Z5g_SINR"), "dB"), rating("nr_sinr", raw.get("Z5g_SINR"))),
        ("5G PCI", hex_to_dec(raw.get("nr5g_pci")), None),
    ]
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "language": language,
        "rows": [
            {
                "name": name,
                "value": value,
                "rating": level,
                "rating_text": RATING_TEXTS[language].get(level, "") if level else "",
                "explanation": EXPLANATIONS[language].get(name, ""),
                "reference_key": REFERENCE_KEYS.get(name),
                "detail": details.get(name),
            }
            for name, value, level in rows
        ],
    }


ANSI = {
    "excellent": "\033[1;32m",
    "good": "\033[32m",
    "fair": "\033[33m",
    "poor": "\033[31m",
    "reset": "\033[0m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}


def render_cli(status, explain=False, use_color=True):
    def c(text, key):
        return f"{ANSI[key]}{text}{ANSI['reset']}" if use_color else text

    language = status.get("language", "en")
    updated_label = "อัปเดต" if language == "th" else "Updated"

    print(c(APP_NAME, "bold"))
    print(f"{updated_label}  {status['timestamp']}")
    print("─" * 58)
    current_group = None
    for row in status["rows"]:
        name = row["name"]
        if name.startswith("LTE ") and current_group != "LTE":
            print("\n" + c("LTE", "bold"))
            current_group = "LTE"
        elif name.startswith("5G ") and current_group != "5G":
            print("\n" + c("5G NR", "bold"))
            current_group = "5G"

        value = row["value"]
        if row["rating"]:
            badge = f"● {row['rating_text']}"
            value = c(value, row["rating"]) + "  " + c(badge, row["rating"])
        print(f"{name:<16} {value}")
        if explain and row["explanation"]:
            print(" " * 18 + c("↳ " + row["explanation"], "dim"))


DASHBOARD_HTML = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZTE CPE Monitor</title>
<style>
:root { color-scheme: light dark; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
body { margin:0; background:#111318; color:#eef1f5; }
.wrap { max-width:1000px; margin:32px auto; padding:0 20px 40px; }
header { display:flex; align-items:end; justify-content:space-between; gap:20px; margin-bottom:20px; }
h1 { margin:0; font-size:30px; }
.sub { color:#9da7b3; margin-top:6px; }
.controls { display:flex; gap:10px; align-items:center; color:#c8d0da; flex-wrap:wrap; }
.controls select,.ref-button { font:inherit; }
.ref-button { border:1px solid #3b4654; background:#202631; color:#e7edf5; border-radius:9px; padding:6px 10px; cursor:pointer; }
.ref-button:hover,.info-button:hover { background:#2a3341; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }
.card { background:#1a1e25; border:1px solid #2a303a; border-radius:14px; padding:16px; }
.card h2 { margin:0 0 12px; font-size:15px; color:#aab4c0; }
.metric { padding:10px 0; border-top:1px solid #282e37; }
.metric:first-of-type { border-top:0; }
.line { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.name-wrap { display:flex; align-items:center; gap:6px; min-width:0; }
.name { color:#bec7d1; }
.info-button { width:21px; height:21px; border-radius:50%; border:1px solid #3b4654; background:#202631; color:#9fc6ff; cursor:pointer; padding:0; line-height:18px; font-weight:700; }
.value { font-size:18px; font-weight:650; font-variant-numeric:tabular-nums; }
.badge { font-size:12px; font-weight:700; padding:3px 8px; border-radius:999px; margin-left:7px; }
.excellent { color:#55dc83; } .badge.excellent,.swatch.excellent { background:#163c25; }
.good { color:#8ee6a8; } .badge.good,.swatch.good { background:#23452d; }
.moderate,.fair { color:#ffd166; } .badge.moderate,.badge.fair,.swatch.moderate,.swatch.fair { background:#433713; }
.poor { color:#ff9f43; } .badge.poor,.swatch.poor { background:#4b3017; }
.very_poor { color:#ff6b6b; } .badge.very_poor,.swatch.very_poor { background:#461d20; }
.explanation { display:none; color:#8f9aa7; font-size:13px; line-height:1.45; margin-top:6px; }
.show-explain .explanation { display:block; }
#error { display:none; background:#461d20; color:#ffb2b2; border-radius:10px; padding:12px 14px; margin-bottom:14px; }
footer { margin-top:18px; color:#77818d; font-size:12px; }
dialog { width:min(880px,calc(100vw - 32px)); max-height:82vh; border:1px solid #384251; border-radius:16px; background:#15191f; color:#eef1f5; padding:0; box-shadow:0 24px 80px #0009; }
dialog::backdrop { background:#05070a99; backdrop-filter:blur(3px); }
.dialog-head { position:sticky; top:0; z-index:2; display:flex; justify-content:space-between; align-items:center; gap:12px; padding:16px 18px; background:#15191f; border-bottom:1px solid #2a303a; }
.dialog-head h2 { margin:0; font-size:19px; }
.close-button { border:0; background:transparent; color:#b9c3cf; font-size:25px; cursor:pointer; }
.ref-body { padding:4px 18px 20px; overflow:auto; }
.ref-section { margin:18px 0 24px; }
.ref-section h3 { margin:0 0 7px; font-size:17px; }
.ref-copy { margin:0 0 12px; color:#aeb8c4; line-height:1.55; }
.current-ref { padding:10px 12px; border:1px solid #35506f; border-radius:10px; background:#182638; margin:10px 0 14px; font-variant-numeric:tabular-nums; }
.table-wrap { overflow-x:auto; border:1px solid #2b333e; border-radius:10px; }
.ref-table { width:100%; border-collapse:collapse; min-width:520px; }
.ref-table th,.ref-table td { text-align:left; padding:9px 10px; border-bottom:1px solid #29313b; font-size:13px; }
.ref-table th { color:#9facba; font-weight:650; background:#1b2028; }
.ref-table tr:last-child td { border-bottom:0; }
.ref-table tr.current td { background:#1b3045; }
.level-cell { display:flex; align-items:center; gap:8px; }
.swatch { width:10px; height:10px; border-radius:50%; border:1px solid #ffffff22; }
.source-note { color:#7f8a97; font-size:12px; line-height:1.45; margin-top:16px; }
@media (max-width:620px) {
  .wrap { margin-top:20px; padding-inline:14px; }
  header { align-items:flex-start; flex-direction:column; }
  .controls { width:100%; }
  .line { align-items:flex-start; }
  .value { font-size:17px; }
}
</style>
</head>
<body><div class="wrap" id="app">
<header>
<div><h1>ZTE CPE Monitor</h1><div class="sub" id="updated"></div></div>
<div class="controls">
<button class="ref-button" id="refButton" type="button">Ref</button>
<label><span id="languageLabel"></span>
<select id="language"><option value="en">English</option><option value="th">ไทย</option></select>
</label>
<label><input id="explain" type="checkbox"> <span id="explainLabel"></span></label>
</div>
</header>
<div id="error"></div>
<div class="grid" id="grid"></div>
<footer id="footer"></footer>
</div>
<dialog id="refDialog">
  <div class="dialog-head"><h2 id="refTitle"></h2><button class="close-button" id="closeRef" type="button" aria-label="Close">×</button></div>
  <div class="ref-body" id="refBody"></div>
</dialog>
<script>
const intervalMs = __INTERVAL_MS__;
const referenceData = __REFERENCE_DATA__;
let currentLang = "__LANG__";
let latestRows = {};
const i18n = {
  en: {
    loading: "Loading signal data…",
    explain: "Show explanations",
    language: "Language",
    connection: "Connection",
    refresh: "refresh",
    error: "Unable to read signal data",
    ref: "Ref",
    refTitle: "Signal & frequency reference",
    detailsFor: "Details for",
    current: "Current",
    rsrpTitle: "RSRP · Signal strength",
    rsrpCopy: "RSRP measures the received reference-signal power. Values closer to 0 dBm mean a stronger radio signal. It tells you strength, not how clean the channel is.",
    sinrTitle: "SINR · Signal quality",
    sinrCopy: "SINR compares the wanted signal with interference and noise. Higher is better. A strong RSRP can still perform poorly when SINR is low.",
    lteBandsTitle: "LTE band codes",
    nrBandsTitle: "5G NR band codes",
    bandCopy: "The band code identifies a standardized frequency range. FDD uses separate uplink/downlink ranges; TDD shares one range in time.",
    channelCopy: "EARFCN / NR-ARFCN is the channel number. The current channel can be converted to an approximate RF reference frequency.",
    level: "Level",
    range: "Range",
    band: "Band",
    common: "Common name",
    duplex: "Duplex",
    uplink: "Uplink MHz",
    downlink: "Downlink / TDD MHz",
    frequency: "frequency",
    downlinkWord: "downlink",
    referenceWord: "reference frequency",
    source: "Reference: 3GPP TS 36.101 for LTE EARFCN and TS 38.104 / 38.101-1 for NR. MC7010 band support varies by hardware revision and firmware.",
    footer: "This dashboard runs only while the zte-cpe command is active. Press Ctrl+C in Terminal to stop it."
  },
  th: {
    loading: "กำลังอ่านข้อมูลสัญญาณ…",
    explain: "แสดงคำอธิบาย",
    language: "ภาษา",
    connection: "การเชื่อมต่อ",
    refresh: "รีเฟรช",
    error: "ไม่สามารถอ่านข้อมูลสัญญาณได้",
    ref: "Ref",
    refTitle: "อ้างอิงค่าสัญญาณและความถี่",
    detailsFor: "รายละเอียด",
    current: "ค่าปัจจุบัน",
    rsrpTitle: "RSRP · ความแรงสัญญาณ",
    rsrpCopy: "RSRP คือกำลังของสัญญาณอ้างอิงที่รับได้ ค่ายิ่งใกล้ 0 dBm ยิ่งแรง ใช้ดูความแรงของสัญญาณ แต่ไม่ได้บอกว่าสัญญาณสะอาดหรือมีคลื่นรบกวนมากแค่ไหน",
    sinrTitle: "SINR · คุณภาพสัญญาณ",
    sinrCopy: "SINR เปรียบเทียบสัญญาณที่ต้องการกับสัญญาณรบกวนและ noise ค่ายิ่งสูงยิ่งดี แม้ RSRP จะแรง แต่ถ้า SINR ต่ำ ความเร็วก็อาจไม่ดีได้",
    lteBandsTitle: "รหัสย่านความถี่ LTE",
    nrBandsTitle: "รหัสย่านความถี่ 5G NR",
    bandCopy: "รหัส Band คือชื่อย่อของช่วงความถี่ตามมาตรฐาน FDD แยกความถี่ขาขึ้น/ขาลง ส่วน TDD ใช้ช่วงเดียวกันสลับกันตามเวลา",
    channelCopy: "EARFCN / NR-ARFCN คือหมายเลขช่องสัญญาณ สามารถนำมาแปลงเป็นความถี่อ้างอิงของช่องที่ใช้อยู่ได้",
    level: "ระดับ",
    range: "ช่วงค่า",
    band: "Band",
    common: "ชื่อความถี่",
    duplex: "ระบบ",
    uplink: "Uplink MHz",
    downlink: "Downlink / TDD MHz",
    frequency: "ความถี่",
    downlinkWord: "ขาลง",
    referenceWord: "ความถี่อ้างอิง",
    source: "อ้างอิง: 3GPP TS 36.101 สำหรับ LTE EARFCN และ TS 38.104 / 38.101-1 สำหรับ NR ทั้งนี้ Band ที่ MC7010 รองรับจริงอาจต่างกันตามรุ่นย่อยและ firmware",
    footer: "Dashboard นี้ทำงานเฉพาะตอนที่คำสั่ง zte-cpe กำลังรันอยู่ กด Ctrl+C ใน Terminal เพื่อหยุด"
  }
};
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function tr(key) { return (i18n[currentLang] || i18n.en)[key] || key; }
function ratingText(key) {
  const map = currentLang === "th"
    ? {excellent:"ดีมาก",good:"ดี",moderate:"ปานกลาง",fair:"พอใช้",poor:"แย่",very_poor:"แย่มาก"}
    : {excellent:"Excellent",good:"Good",moderate:"Moderate",fair:"Fair",poor:"Poor",very_poor:"Very poor"};
  return map[key] || key;
}
function applyLanguage() {
  document.documentElement.lang = currentLang;
  document.getElementById("language").value = currentLang;
  document.getElementById("languageLabel").textContent = tr("language") + ": ";
  document.getElementById("explainLabel").textContent = tr("explain");
  document.getElementById("refButton").textContent = tr("ref");
  document.getElementById("refTitle").textContent = tr("refTitle");
  document.getElementById("footer").textContent = tr("footer");
  document.getElementById("updated").textContent = tr("loading");
}
document.getElementById("explain").addEventListener("change", e => {
  document.getElementById("app").classList.toggle("show-explain", e.target.checked);
});
document.getElementById("language").addEventListener("change", async e => {
  currentLang = e.target.value;
  applyLanguage();
  try {
    await fetch("/api/language", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({language: currentLang})
    });
  } catch (_) {}
  refresh();
});
function groupFor(name) {
  if (name.startsWith("LTE ")) return "LTE";
  if (name.startsWith("5G ")) return "5G NR";
  return tr("connection");
}
function signalTable(metric) {
  const rows = referenceData.signal[metric] || [];
  return '<div class="table-wrap"><table class="ref-table"><thead><tr><th>'+esc(tr("level"))+'</th><th>'+esc(tr("range"))+'</th></tr></thead><tbody>' +
    rows.map(row => '<tr><td><span class="level-cell"><span class="swatch '+esc(row.rating)+'"></span><span class="'+esc(row.rating)+'">'+esc(ratingText(row.rating))+'</span></span></td><td>'+esc(row.range)+'</td></tr>').join("") +
    '</tbody></table></div>';
}
function currentBand(kind) {
  const row = latestRows[kind === "lte" ? "LTE Band" : "5G Band"];
  return row && row.value ? String(row.value).toLowerCase() : "";
}
function bandTable(kind) {
  const rows = kind === "lte" ? referenceData.lte_bands : referenceData.nr_bands;
  const current = currentBand(kind);
  return '<div class="table-wrap"><table class="ref-table"><thead><tr><th>'+esc(tr("band"))+'</th><th>'+esc(tr("common"))+'</th><th>'+esc(tr("duplex"))+'</th><th>'+esc(tr("uplink"))+'</th><th>'+esc(tr("downlink"))+'</th></tr></thead><tbody>' +
    rows.map(row => '<tr class="'+(String(row.band).toLowerCase() === current ? 'current' : '')+'"><td><strong>'+esc(row.band)+'</strong></td><td>'+esc(row.name)+'</td><td>'+esc(row.duplex)+'</td><td>'+esc(row.uplink)+'</td><td>'+esc(row.downlink)+'</td></tr>').join("") +
    '</tbody></table></div>';
}
function currentDetail(rowName) {
  const row = latestRows[rowName];
  if (!row || !row.detail) return "";
  const d = row.detail;
  if (d.frequency_mhz != null) {
    const dir = d.direction === "downlink" ? tr("downlinkWord") : tr("referenceWord");
    return '<div class="current-ref"><strong>'+esc(tr("current"))+':</strong> ' +
      (d.band ? esc(d.band)+' · ' : '') + esc(d.frequency_mhz) + ' MHz · ' + esc(dir) + '</div>';
  }
  if (d.band) {
    return '<div class="current-ref"><strong>'+esc(tr("current"))+':</strong> '+esc(d.band)+' · '+esc(d.name)+' · '+esc(d.duplex)+' · '+esc(d.downlink)+' MHz</div>';
  }
  return "";
}
function signalSection(metric) {
  const title = metric === "rsrp" ? tr("rsrpTitle") : tr("sinrTitle");
  const copy = metric === "rsrp" ? tr("rsrpCopy") : tr("sinrCopy");
  return '<section class="ref-section"><h3>'+esc(title)+'</h3><p class="ref-copy">'+esc(copy)+'</p>'+signalTable(metric)+'</section>';
}
function bandSection(kind, rowName) {
  const title = kind === "lte" ? tr("lteBandsTitle") : tr("nrBandsTitle");
  return '<section class="ref-section"><h3>'+esc(title)+'</h3><p class="ref-copy">'+esc(tr("bandCopy"))+'</p>'+currentDetail(rowName)+bandTable(kind)+'</section>';
}
function channelSection(kind, rowName) {
  return '<section class="ref-section"><h3>'+(kind === "lte" ? 'LTE EARFCN' : '5G NR-ARFCN')+'</h3><p class="ref-copy">'+esc(tr("channelCopy"))+'</p>'+currentDetail(rowName)+bandTable(kind)+'</section>';
}
function openReference(key="overview", rowName="") {
  let body = "";
  if (key === "rsrp") body = signalSection("rsrp");
  else if (key === "sinr") body = signalSection("sinr");
  else if (key === "lte_band") body = bandSection("lte", rowName || "LTE Band");
  else if (key === "nr_band") body = bandSection("nr", rowName || "5G Band");
  else if (key === "lte_channel") body = channelSection("lte", rowName || "LTE EARFCN");
  else if (key === "nr_channel") body = channelSection("nr", rowName || "5G NR-ARFCN");
  else body = signalSection("rsrp") + signalSection("sinr") + bandSection("lte", "LTE Band") + bandSection("nr", "5G Band");
  document.getElementById("refBody").innerHTML = body + '<p class="source-note">'+esc(tr("source"))+'</p>';
  document.getElementById("refDialog").showModal();
}
document.getElementById("refButton").addEventListener("click", () => openReference());
document.getElementById("closeRef").addEventListener("click", () => document.getElementById("refDialog").close());
document.getElementById("refDialog").addEventListener("click", e => {
  if (e.target === e.currentTarget) e.currentTarget.close();
});
document.getElementById("grid").addEventListener("click", e => {
  const button = e.target.closest("[data-ref]");
  if (button) openReference(button.dataset.ref, button.dataset.row);
});
async function refresh() {
  try {
    const r = await fetch("/api/status?lang=" + encodeURIComponent(currentLang), {cache:"no-store"});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || tr("error"));
    document.getElementById("error").style.display = "none";
    document.getElementById("updated").textContent = "Updated " + data.timestamp + " · " + tr("refresh") + " " + (intervalMs/1000) + "s";
    const groups = {};
    latestRows = {};
    for (const row of data.rows) {
      latestRows[row.name] = row;
      (groups[groupFor(row.name)] ||= []).push(row);
    }
    document.getElementById("grid").innerHTML = Object.entries(groups).map(([g, rows]) =>
      '<section class="card"><h2>'+esc(g)+'</h2>' + rows.map(row => {
        const cls = row.rating || "";
        const badge = row.rating_text ? '<span class="badge '+cls+'">'+esc(row.rating_text)+'</span>' : "";
        const info = row.reference_key ? '<button type="button" class="info-button" data-ref="'+esc(row.reference_key)+'" data-row="'+esc(row.name)+'" aria-label="'+esc(tr("detailsFor")+' '+row.name)+'">i</button>' : "";
        return '<div class="metric"><div class="line"><span class="name-wrap"><span class="name">'+esc(row.name)+'</span>'+info+'</span><span><span class="value '+cls+'">'+esc(row.value)+'</span>'+badge+'</span></div>' +
          (row.explanation ? '<div class="explanation">'+esc(row.explanation)+'</div>' : '') + '</div>';
      }).join("") + '</section>'
    ).join("");
  } catch(e) {
    const box = document.getElementById("error");
    box.textContent = e.message || tr("error");
    box.style.display = "block";
  }
}
applyLanguage();
refresh();
setInterval(refresh, intervalMs);
</script></body></html>"""


def serve_dashboard(client, port, interval, open_browser, language="en"):
    interval = max(2, interval)
    state = {"language": language if language in LANGUAGES else "en"}
    page = (
        DASHBOARD_HTML
        .replace("__INTERVAL_MS__", str(interval * 1000))
        .replace("__LANG__", state["language"])
        .replace("__REFERENCE_DATA__", json.dumps(REFERENCE_DATA, ensure_ascii=False))
    )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def send_json(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/status":
                try:
                    query = urllib.parse.parse_qs(parsed.query)
                    requested = query.get("lang", [state["language"]])[0]
                    lang = requested if requested in LANGUAGES else state["language"]
                    payload = normalize(client.raw_status(), lang)
                    self.send_json(payload)
                except Exception as e:
                    self.send_json({"error": str(e)}, 503)
                return

            body = page.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != "/api/language":
                self.send_json({"error": "Not found"}, 404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                lang = str(payload.get("language", "")).lower()
                if lang not in LANGUAGES:
                    self.send_json({"error": "Language must be 'en' or 'th'"}, 400)
                    return
                config_save(language=lang)
                state["language"] = lang
                self.send_json({"language": lang})
            except Exception as e:
                self.send_json({"error": str(e)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    stop_text = "กด Ctrl+C เพื่อหยุด" if state["language"] == "th" else "Press Ctrl+C to stop"
    print(f"ZTE CPE dashboard: {url}")
    print(f"Refresh every {interval}s · {stop_text}")
    if open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("\nDashboard stopped." if state["language"] == "en" else "\nหยุด Dashboard แล้ว")


def get_client_password(force_prompt=False):
    stored = None if force_prompt else credential_get()
    if stored:
        return stored, True
    password = getpass.getpass("ZTE CPE password: ")
    if not password:
        raise ZTECPEError("ไม่ได้ป้อนรหัสผ่าน")
    return password, False


def parser():
    p = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description="On-demand ZTE CPE status CLI / temporary dashboard",
    )
    p.add_argument("-e", "--explain", action="store_true", help="show an explanation for each value")
    p.add_argument("--json", action="store_true", help="output JSON")
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    sub = p.add_subparsers(dest="command")
    d = sub.add_parser("dashboard", help="open a temporary dashboard")
    d.add_argument("--interval", type=int, default=10, help="refresh interval in seconds (default: 10)")
    d.add_argument("--port", type=int, default=8765, help="port (default: 8765)")
    d.add_argument("--no-open", action="store_true", help="do not open the browser automatically")

    sub.add_parser("setup", help="set both Admin URL and password")

    u = sub.add_parser("url", help="show or change the Admin URL")
    u.add_argument("admin_url", nargs="?", help="new Admin URL, e.g. http://192.168.0.1")

    l = sub.add_parser("language", aliases=["lang"], help="show or change language (en/th)")
    l.add_argument("language", nargs="?", choices=LANGUAGES, help="en or th")

    sub.add_parser("password", help="change the password stored in the secure credential store")
    sub.add_parser("config", help="show current config without revealing the password")
    sub.add_parser("detect", help="detect model and API adapter")
    sub.add_parser("capabilities", help="probe read-only API capabilities")
    sub.add_parser("telemetry", help="show read-only connection and traffic telemetry")
    sb = sub.add_parser("support-bundle", help="write a privacy-safe diagnostic bundle")
    sb.add_argument("--output", help="output JSON path (default: ./zte-cpe-support.json)")
    sub.add_parser("forget-password", help="remove the ZTE CPE password from the secure credential store")
    return p


def main():
    args = parser().parse_args()
    language = saved_language()

    if args.command == "forget-password":
        p = credential_delete()
        if p.returncode == 0:
            print(
                "Removed the ZTE CPE password from the secure credential store"
                if language == "en"
                else "ลบรหัสผ่าน ZTE CPE ออกจาก secure credential store แล้ว"
            )
            return 0
        print(
            "No ZTE CPE password found in Keychain"
            if language == "en"
            else "ไม่พบรหัสผ่าน ZTE CPE ใน Keychain",
            file=sys.stderr,
        )
        return 1

    if args.command == "detect":
        admin_url, password, client = load_runtime_credentials()
        info = client.device_info()
        print(f"Model: {info['model']}")
        print(f"Hardware: {info['hardware_version'] or '—'}")
        print(f"Firmware: {info['firmware_version'] or '—'}")
        print(f"Web UI: {info['web_version'] or '—'}")
        print(f"API adapter: {info['api_adapter']}")
        return 0

    if args.command == "capabilities":
        admin_url, password, client = load_runtime_credentials()
        info = client.device_info()
        print(f"Model: {info['model']}")
        print(f"API adapter: {info['api_adapter']}")
        print("\nCapabilities")
        print("─" * 46)
        for name, cap in client.capabilities().items():
            marker = "✓" if cap["state"] == "available" else ("○" if cap["state"] == "present-empty" else "—")
            print(f"{marker} {name:<22} {cap['state']}")
        return 0

    if args.command == "telemetry":
        admin_url, password, client = load_runtime_credentials()
        raw = client.telemetry()
        print("Connection")
        print("─" * 46)
        print(f"WAN status        {raw.get('wan_connect_status') or '—'}")
        print(f"PPP status        {raw.get('ppp_status') or '—'}")
        print(f"Session uptime    {human_duration(raw.get('realtime_time'))}")
        print("\nRealtime traffic")
        print("─" * 46)
        print(f"TX total          {human_bytes(raw.get('realtime_tx_bytes'))}")
        print(f"RX total          {human_bytes(raw.get('realtime_rx_bytes'))}")
        print(f"TX rate           {human_rate(raw.get('realtime_tx_thrpt'))}")
        print(f"RX rate           {human_rate(raw.get('realtime_rx_thrpt'))}")
        print("\nMonthly traffic")
        print("─" * 46)
        print(f"TX                {human_bytes(raw.get('monthly_tx_bytes'))}")
        print(f"RX                {human_bytes(raw.get('monthly_rx_bytes'))}")
        print(f"Connected time    {human_duration(raw.get('monthly_time'))}")
        return 0

    if args.command == "support-bundle":
        admin_url, password, client = load_runtime_credentials()
        bundle = client.support_bundle()
        output = pathlib.Path(args.output or "zte-cpe-support.json").expanduser()
        output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
        print(f"Wrote privacy-safe support bundle: {output}")
        print("No password, cookies, IP/MAC addresses, cell IDs, SSIDs, hostnames, or raw radio values are included.")
        return 0

    if args.command == "config":
        admin_url = saved_admin_url()
        print(f"Admin URL: {admin_url or '(not configured)'}")
        print(f"Language: {saved_language()}")
        print(f"Password: {'stored securely' if credential_get() else '(not stored)'}")
        print(f"Config file: {CONFIG_FILE}")
        return 0

    if args.command in ("language", "lang"):
        if args.language is None:
            print(saved_language())
            return 0
        config_save(language=args.language)
        print(
            f"Language changed to {'English' if args.language == 'en' else 'ไทย'}"
            if language == "en"
            else f"เปลี่ยนภาษาเป็น {'English' if args.language == 'en' else 'ไทย'} แล้ว"
        )
        return 0

    if args.command == "setup":
        default_url = saved_admin_url() or BASE_URL
        admin_url = prompt_admin_url(default_url, language)
        password = getpass.getpass("ZTE CPE password: ")
        if not password:
            raise ZTECPEError("No password entered" if language == "en" else "ไม่ได้ป้อนรหัสผ่าน")
        validate_credentials(admin_url, password)
        config_save(admin_url=admin_url)
        credential_set(password)
        if language == "en":
            print(f"✓ Saved Admin URL: {admin_url}")
            print("✓ Verified and saved password in the secure credential store")
        else:
            print(f"✓ บันทึก Admin URL: {admin_url}")
            print("✓ ตรวจสอบและบันทึกรหัสผ่านลง secure credential store แล้ว")
        return 0

    if args.command == "url":
        current = saved_admin_url()
        if args.admin_url is None and current:
            print(f"Current Admin URL: {current}")
            prompt = "New Admin URL (press Enter to keep current): " if language == "en" else "New Admin URL (กด Enter เพื่อไม่เปลี่ยน): "
            new_value = input(prompt).strip()
            if not new_value:
                return 0
            admin_url = normalize_admin_url(new_value)
        else:
            prompt = "New Admin URL: "
            admin_url = normalize_admin_url(args.admin_url or input(prompt).strip())

        password = credential_get()
        if password:
            validate_credentials(admin_url, password)
        else:
            prompt = "ZTE CPE password (used to verify URL): " if language == "en" else "ZTE CPE password (ใช้ตรวจสอบ URL): "
            password = getpass.getpass(prompt)
            if not password:
                raise ZTECPEError("No password entered" if language == "en" else "ไม่ได้ป้อนรหัสผ่าน")
            validate_credentials(admin_url, password)
            credential_set(password)
        config_save(admin_url=admin_url)
        print(
            f"✓ Admin URL changed to {admin_url}"
            if language == "en"
            else f"✓ เปลี่ยน Admin URL เป็น {admin_url}"
        )
        return 0

    if args.command == "password":
        admin_url = saved_admin_url()
        if not admin_url:
            print(
                "No Admin URL configured; starting URL setup first"
                if language == "en"
                else "ยังไม่มี Admin URL; เริ่ม setup URL ก่อน"
            )
            admin_url = prompt_admin_url(BASE_URL, language)
        password = getpass.getpass("New ZTE CPE password: ")
        if not password:
            raise ZTECPEError("No password entered" if language == "en" else "ไม่ได้ป้อนรหัสผ่าน")
        validate_credentials(admin_url, password)
        if not saved_admin_url():
            config_save(admin_url=admin_url)
        credential_set(password)
        print(
            "✓ Password verified and saved in the secure credential store"
            if language == "en"
            else "✓ ตรวจสอบรหัสผ่านสำเร็จและบันทึกลง secure credential store แล้ว"
        )
        return 0

    admin_url, password, client = load_runtime_credentials()
    raw = client.raw_status()
    language = saved_language()

    if args.command == "dashboard":
        serve_dashboard(
            client,
            args.port,
            args.interval,
            not args.no_open,
            language=language,
        )
        return 0

    status = normalize(raw, language)
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        use_color = (not args.no_color) and sys.stdout.isatty()
        render_cli(status, explain=args.explain, use_color=use_color)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ZTECPEError as e:
        print(f"{COMMAND_NAME}: {e}", file=sys.stderr)
        if credential_get():
            print("ถ้ารหัสผ่านถูกเปลี่ยน ให้รัน: zte-cpe password", file=sys.stderr)
        raise SystemExit(2)
    except KeyboardInterrupt:
        raise SystemExit(130)
