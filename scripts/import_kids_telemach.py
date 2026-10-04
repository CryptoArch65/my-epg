#!/usr/bin/env python3
"""Finalize selected kids channels from canonical Telemach feeds.

The grabber stores each Telemach source under a canonical helper ID. This script
copies that Telemach schedule onto the playlist-facing IDs, downloads the
source-native Telemach logos, hosts them in this repository, and forces those
hosted logos into guide.xml. It is intentionally safe to run again after other
EPG writers so Telemach remains the final source for these channels.
"""

from __future__ import annotations

import copy
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
        "source_id": "NickJrTelemach.ba",
        "site_id": "922",
        "display": "NICK JR(HR)",
        "logo_file": "telemach-922.png",
    },
    "NickJr.rs": {
        "source_id": "NickJrTelemach.ba",
        "site_id": "922",
        "display": "NICK JR(SR)",
        "logo_file": "telemach-922.png",
    },
    "PinkSuperKids.rs": {
        "source_id": "PinkSuperKidsTelemach.ba",
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


def copy_schedule(root, source_id: str, target_id: str, display: str) -> int:
    channels = {c.get("id"): c for c in root.findall("channel")}
    source = channels.get(source_id)
    if source is None:
        raise ValueError(f"Missing Telemach source channel {source_id}")

    source_programmes = [
        p for p in root.findall("programme") if p.get("channel") == source_id
    ]
    if not source_programmes:
        raise ValueError(f"{source_id} has 0 Telemach programmes")

    target = channels.get(target_id)
    if target is None:
        target = copy.deepcopy(source)
        target.set("id", target_id)
        root.insert(len(root.findall("channel")), target)
    else:
        for child in list(target):
            target.remove(child)
        for child in source:
            target.append(copy.deepcopy(child))

    for programme in list(root.findall("programme")):
        if programme.get("channel") == target_id:
            root.remove(programme)

    for programme in source_programmes:
        clone = copy.deepcopy(programme)
        clone.set("channel", target_id)
        root.append(clone)

    names = {(n.text or "").strip() for n in target.findall("display-name")}
    if display not in names:
        ET.SubElement(target, "display-name").text = display

    return len(source_programmes)


def main(guide_path: Path, config_path: Path, logos_dir: Path) -> None:
    tree = ET.parse(guide_path)
    root = tree.getroot()
    catalog = telemach_catalog(config_path)
    hosted = {}

    for channel_id, cfg in CHANNELS.items():
        count = copy_schedule(root, cfg["source_id"], channel_id, cfg["display"])
        channel = next(c for c in root.findall("channel") if c.get("id") == channel_id)

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

        print(
            f"Telemach kids {channel_id}: source={cfg['source_id']}, "
            f"site_id={site_id}, programmes={count}, source_logo={hosted[site_id]}, "
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
