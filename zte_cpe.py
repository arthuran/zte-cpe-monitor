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

VERSION = "0.2.0"
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
        "fair": "Fair",
        "poor": "Poor",
        "unknown": "No data",
    },
    "th": {
        "excellent": "ดีมาก",
        "good": "ดี",
        "fair": "พอใช้",
        "poor": "แย่",
        "unknown": "ไม่มีข้อมูล",
    },
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
        if x >= 20:
            return "excellent"
        if x >= 13:
            return "good"
        if x >= 0:
            return "fair"
        return "poor"
    if metric == "lte_rsrq":
        if x >= -10:
            return "excellent"
        if x >= -15:
            return "good"
        if x >= -20:
            return "fair"
        return "poor"
    return "unknown"


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

    rows = [
        ("Mode", mode, None),
        ("Signal bars", fmt(raw.get("signalbar"), "/5"), None),
        ("LTE Band", clean_band(raw.get("wan_active_band"), "LTE"), None),
        ("LTE EARFCN", fmt(raw.get("wan_active_channel")), None),
        ("LTE RSRP", fmt(raw.get("lte_rsrp"), "dBm"), rating("lte_rsrp", raw.get("lte_rsrp"))),
        ("LTE RSRQ", fmt(raw.get("lte_rsrq"), "dB"), rating("lte_rsrq", raw.get("lte_rsrq"))),
        ("LTE SINR", fmt(raw.get("lte_snr"), "dB"), rating("lte_sinr", raw.get("lte_snr"))),
        ("LTE RSSI", fmt(raw.get("lte_rssi"), "dBm"), None),
        ("LTE PCI", hex_to_dec(raw.get("lte_pci")), None),
        ("LTE Cell ID", hex_to_dec(raw.get("cell_id")), None),
        ("LTE CA", ca, None),
        ("5G Band", clean_band(raw.get("nr5g_action_band"), "NR"), None),
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
.controls { display:flex; gap:14px; align-items:center; color:#c8d0da; flex-wrap:wrap; }
.controls select { font:inherit; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }
.card { background:#1a1e25; border:1px solid #2a303a; border-radius:14px; padding:16px; }
.card h2 { margin:0 0 12px; font-size:15px; color:#aab4c0; }
.metric { padding:10px 0; border-top:1px solid #282e37; }
.metric:first-of-type { border-top:0; }
.line { display:flex; justify-content:space-between; gap:12px; align-items:center; }
.name { color:#bec7d1; }
.value { font-size:18px; font-weight:650; font-variant-numeric:tabular-nums; }
.badge { font-size:12px; font-weight:700; padding:3px 8px; border-radius:999px; margin-left:7px; }
.excellent,.good { color:#55dc83; } .badge.excellent,.badge.good { background:#163c25; }
.fair { color:#ffd166; } .badge.fair { background:#433713; }
.poor { color:#ff6b6b; } .badge.poor { background:#461d20; }
.explanation { display:none; color:#8f9aa7; font-size:13px; line-height:1.45; margin-top:6px; }
.show-explain .explanation { display:block; }
#error { display:none; background:#461d20; color:#ffb2b2; border-radius:10px; padding:12px 14px; margin-bottom:14px; }
footer { margin-top:18px; color:#77818d; font-size:12px; }
</style>
</head>
<body><div class="wrap" id="app">
<header>
<div><h1>ZTE CPE Monitor</h1><div class="sub" id="updated"></div></div>
<div class="controls">
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
<script>
const intervalMs = __INTERVAL_MS__;
let currentLang = "__LANG__";
const i18n = {
  en: {
    loading: "Loading signal data…",
    explain: "Show explanations",
    language: "Language",
    connection: "Connection",
    refresh: "refresh",
    error: "Unable to read signal data",
    footer: "This dashboard runs only while the zte-cpe command is active. Press Ctrl+C in Terminal to stop it."
  },
  th: {
    loading: "กำลังอ่านข้อมูลสัญญาณ…",
    explain: "แสดงคำอธิบาย",
    language: "ภาษา",
    connection: "การเชื่อมต่อ",
    refresh: "รีเฟรช",
    error: "ไม่สามารถอ่านข้อมูลสัญญาณได้",
    footer: "Dashboard นี้ทำงานเฉพาะตอนที่คำสั่ง zte-cpe กำลังรันอยู่ กด Ctrl+C ใน Terminal เพื่อหยุด"
  }
};
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\\"":"&quot;","'":"&#39;"}[c]));
function tr(key) { return (i18n[currentLang] || i18n.en)[key] || key; }
function applyLanguage() {
  document.documentElement.lang = currentLang;
  document.getElementById("language").value = currentLang;
  document.getElementById("languageLabel").textContent = tr("language") + ": ";
  document.getElementById("explainLabel").textContent = tr("explain");
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
async function refresh() {
  try {
    const r = await fetch("/api/status?lang=" + encodeURIComponent(currentLang), {cache:"no-store"});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || tr("error"));
    document.getElementById("error").style.display = "none";
    document.getElementById("updated").textContent = "Updated " + data.timestamp + " · " + tr("refresh") + " " + (intervalMs/1000) + "s";
    const groups = {};
    for (const row of data.rows) (groups[groupFor(row.name)] ||= []).push(row);
    document.getElementById("grid").innerHTML = Object.entries(groups).map(([g, rows]) =>
      '<section class="card"><h2>'+esc(g)+'</h2>' + rows.map(row => {
        const cls = row.rating || "";
        const badge = row.rating_text ? '<span class="badge '+cls+'">'+esc(row.rating_text)+'</span>' : "";
        return '<div class="metric"><div class="line"><span class="name">'+esc(row.name)+'</span><span><span class="value '+cls+'">'+esc(row.value)+'</span>'+badge+'</span></div>' +
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
