#!/usr/bin/env python3
"""Generate README screenshots with Codeshot, then align terminal output colors with zte-cpe."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import re
import subprocess
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
APP = ROOT / "zte_cpe.py"

spec = importlib.util.spec_from_file_location("zte_cpe", APP)
zte = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zte)

DEFAULT = "#d6deeb"
GREEN = "#50fa7b"
YELLOW = "#f1fa8c"
RED = "#ff5555"
DIM = "#7f8c9d"
RATING_COLORS = {
    "Excellent": GREEN,
    "Good": GREEN,
    "Fair": YELLOW,
    "Poor": RED,
}


def sample_cli_text() -> str:
    # Synthetic values only. The structure is rendered by the real application code.
    raw = {
        "wan_active_channel": "1275",
        "wan_active_band": "LTE BAND 3",
        "lte_rssi": "-43",
        "lte_rsrp": "-72",
        "lte_snr": "22.2",
        "lte_rsrq": "-11",
        "lte_pci": "7b",
        "cell_id": "1a2b3c",
        "nr5g_action_channel": "518000",
        "nr5g_action_band": "n41",
        "Z5g_rsrp": "-67",
        "Z5g_SINR": "26.5",
        "nr5g_pci": "1f4",
        "wan_lte_ca": "",
        "lte_multi_ca_scell_info": "",
        "network_type": "ENDC",
        "signalbar": "5",
    }
    status = zte.normalize(raw, "en")
    status["timestamp"] = "2026-09-20 16:20:00"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        zte.render_cli(status, explain=False, use_color=False)
    return "$ zte-cpe\n" + buf.getvalue()


def install_text() -> str:
    return """$ brew install arthuran/tap/zte-cpe-monitor
$ zte-cpe setup
ZTE CPE admin URL [http://192.168.0.1]:
ZTE CPE password:
✓ Saved Admin URL: http://192.168.0.1
✓ Verified and saved password in the secure credential store

$ zte-cpe dashboard
ZTE CPE dashboard: http://127.0.0.1:8765/
Refresh every 10s · Press Ctrl+C to stop
"""


def run_codeshot(source: pathlib.Path, output: pathlib.Path, *, theme: str, bg: str, title: str, label: str, width: int) -> None:
    subprocess.run(
        [
            "codeshot", "--preset", "terminal", "--theme", theme, "--bg", bg,
            "--title", title, "--label", label, "--width", str(width),
            "--font-size", "14", str(source), "-o", str(output),
        ],
        cwd=ROOT,
        check=True,
    )


def local(tag: str) -> str:
    return tag.split("}")[-1]


def flatten_text(element: ET.Element, text: str, *, fill: str = DEFAULT, bold: bool = False) -> None:
    for child in list(element):
        element.remove(child)
    element.text = text
    element.set("fill", fill)
    if bold:
        element.set("font-weight", "700")
    elif "font-weight" in element.attrib:
        del element.attrib["font-weight"]


def colored_metric(element: ET.Element, line: str) -> bool:
    m = re.match(
        r"^(?P<label>.+?\s{2,})(?P<value>-?\d+(?:\.\d+)?\s+(?:dBm|dB))(?P<badge>\s+●\s+(?P<rating>Excellent|Good|Fair|Poor))$",
        line,
    )
    if not m:
        return False
    color = RATING_COLORS[m.group("rating")]
    for child in list(element):
        element.remove(child)
    element.text = None
    label = ET.SubElement(element, "tspan")
    label.set("fill", DEFAULT)
    label.text = m.group("label")
    value = ET.SubElement(element, "tspan")
    value.set("fill", color)
    value.text = m.group("value") + m.group("badge")
    element.set("fill", DEFAULT)
    return True


def style_svg(path: pathlib.Path, *, mode: str) -> None:
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    tree = ET.parse(path)
    root = tree.getroot()

    prompt_count = 0
    for element in root.iter():
        if local(element.tag) != "text":
            continue
        full = "".join(element.itertext()).strip("\n")
        if not full:
            continue

        # Codeshot terminal-body lines use this monospaced font and start at x=64.
        is_body = element.attrib.get("x") == "64" and "Cascadia Code" in element.attrib.get("font-family", "")
        if not is_body:
            continue

        if full.startswith("$ "):
            prompt_count += 1
            continue  # retain Codeshot's shell-command highlighting

        if mode == "cli":
            if colored_metric(element, full):
                continue
            if full in {zte.APP_NAME, "LTE", "5G NR"}:
                flatten_text(element, full, bold=True)
            else:
                # Real zte-cpe leaves ordinary values in the terminal's normal foreground.
                flatten_text(element, full)
        else:
            # Install output is mostly normal foreground. Success lines are green in a real terminal-like view.
            if full.startswith("✓"):
                flatten_text(element, full, fill=GREEN)
            else:
                flatten_text(element, full)

    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    cli_txt = DOCS / "cli-sample.txt"
    install_txt = DOCS / "install-sample.txt"
    cli_svg = DOCS / "cli.svg"
    install_svg = DOCS / "install.svg"

    cli_txt.write_text(sample_cli_text(), encoding="utf-8")
    install_txt.write_text(install_text(), encoding="utf-8")

    run_codeshot(cli_txt, cli_svg, theme="nightOwl", bg="tide", title=zte.APP_NAME,
                 label="On-demand signal status", width=980)
    style_svg(cli_svg, mode="cli")

    run_codeshot(install_txt, install_svg, theme="dracula", bg="darkroom", title="Install & run",
                 label="Homebrew", width=900)
    style_svg(install_svg, mode="install")

    print(cli_svg)
    print(install_svg)
