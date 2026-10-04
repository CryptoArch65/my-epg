#!/usr/bin/env python3
"""Finalize selected kids channels with source-native Telemach logos.

EPG rows are grabbed by iptv-org from epg.telemach.ba. This script verifies
that the Telemach schedules are present, downloads the matching Telemach logos,
hosts them in this repository, and forces those hosted logos into guide.xml.
"""

from __future__ import annotations

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from PIL import Image

IMAGE_HOST = "https://images-web.ug-be.cdn.united.cloud"
RAW_BASE = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos"

CHANNELS = {
    "NickJr.hr": {
        "site_id": "922",
        "display": "NICK JR(HR)",
        "logo_file": "telemach-922.png",
    },
    "NickJr.rs": {
        "site_id": "922",
        "display": "NICK JR(SR)",
        "logo_file": "telemach-922.png",
    },
    "PinkSuperKids.rs": {
        "site_id": "1879",
        "display": "SUPER KIDS",
        "logo_file": "telemach-1879.png",
    },
}


def request_json(url: str, headers=None, data=None):
    req = Request(url, headers=headers or {}, data=data)
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def telemach_catalog(config_path: Path):
    script = config_path.read_text(encoding="utf-8")
    match = re.search(r"const BASIC_TOKEN\s*=\s*'([^']+)'", script)
    if not match:
        raise ValueError("Telemach auth token not found in upstream config")

    token = request_json(
        "https://api-web.ug-be.cdn.united.cloud/oauth/token?grant_type=client_credentials",
        {"Authorization": f"Basic {match.group(1)}", "Content-Type": "application/json"},
        data=b"{}",
    )["access_token"]

    return request_json(
        "https://api-web.ug-be.cdn.united.cloud/v1/public/channels"
        "?channelType=TV&communityId=12&languageId=59&imageSize=L",
        {"Authorization": f"Bearer {token}"},
    )


def source_logo(catalog, site_id: str) -> str:
    row = next((item for item in catalog if str(item.get("id")) == site_id), None)
    if row is None:
        raise ValueError(f"Telemach channel {site_id} missing from catalogue")

    images = [
        item for item in (row.get("images") or [])
        if isinstance(item, dict) and item.get("path")
    ]
    images.sort(key=lambda item: (
        "LOGO" not in str(item.get("type", "")).upper(),
        "LOGO" not in str(item.get("legacyType", "")).upper(),
    ))
    if not images:
        raise ValueError(f"Telemach channel {site_id} has no logo")
    return urljoin(IMAGE_HOST, images[0]["path"])


def download_png(url: str, destination: Path) -> None:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        data = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGBA").save(destination, "PNG")


def main(guide_path: Path, config_path: Path, logos_dir: Path) -> None:
    tree = ET.parse(guide_path)
    root = tree.getroot()
    channels = {c.get("id"): c for c in root.findall("channel")}
    counts = Counter(p.get("channel") for p in root.findall("programme"))
    catalog = telemach_catalog(config_path)
    hosted = {}

    for channel_id, cfg in CHANNELS.items():
        channel = channels.get(channel_id)
        if channel is None:
            raise ValueError(f"Missing {channel_id} after Telemach grab")
        if counts[channel_id] == 0:
            raise ValueError(f"{channel_id} has 0 Telemach programmes")

        site_id = cfg["site_id"]
        logo_file = cfg["logo_file"]
        if site_id not in hosted:
            logo = source_logo(catalog, site_id)
            download_png(logo, logos_dir / logo_file)
            hosted[site_id] = logo

        raw_logo = f"{RAW_BASE}/{logo_file}"
        for icon in list(channel.findall("icon")):
            channel.remove(icon)
        ET.SubElement(channel, "icon", {"src": raw_logo})

        names = {(n.text or "").strip() for n in channel.findall("display-name")}
        if cfg["display"] not in names:
            ET.SubElement(channel, "display-name").text = cfg["display"]

        print(
            f"Telemach kids {channel_id}: site_id={site_id}, "
            f"programmes={counts[channel_id]}, source_logo={hosted[site_id]}, "
            f"hosted_logo={raw_logo}"
        )

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "Usage: import_kids_telemach.py guide.xml telemach.config.js logos_dir"
        )
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
