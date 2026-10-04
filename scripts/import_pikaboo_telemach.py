#!/usr/bin/env python3
"""Attach a stable hosted Telemach logo to Pikaboo after its EPG grab."""

from __future__ import annotations

import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from PIL import Image

CHANNEL_ID = "Pikaboo.ba"
SITE_ID = "921"
IMAGE_HOST = "https://images-web.ug-be.cdn.united.cloud"
RAW_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/telemach-921.png"


def request_json(url: str, headers=None, data=None):
    req = Request(url, headers=headers or {}, data=data)
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def telemach_logo(config_path: Path) -> str:
    script = config_path.read_text(encoding="utf-8")
    match = re.search(r"const BASIC_TOKEN\s*=\s*'([^']+)'", script)
    if not match:
        raise ValueError("Telemach auth token not found")

    token = request_json(
        "https://api-web.ug-be.cdn.united.cloud/oauth/token?grant_type=client_credentials",
        {"Authorization": f"Basic {match.group(1)}", "Content-Type": "application/json"},
        data=b"{}",
    )["access_token"]

    channels = request_json(
        "https://api-web.ug-be.cdn.united.cloud/v1/public/channels"
        "?channelType=TV&communityId=12&languageId=59&imageSize=L",
        {"Authorization": f"Bearer {token}"},
    )
    row = next((item for item in channels if str(item.get("id")) == SITE_ID), None)
    if row is None:
        raise ValueError("Pikaboo missing from Telemach catalogue")

    images = [item for item in (row.get("images") or []) if isinstance(item, dict) and item.get("path")]
    images.sort(key=lambda item: (
        "LOGO" not in str(item.get("type", "")).upper(),
        "LOGO" not in str(item.get("legacyType", "")).upper(),
    ))
    if not images:
        raise ValueError("Pikaboo has no Telemach logo")
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
    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        raise ValueError(f"Missing {CHANNEL_ID} after Telemach grab")

    programmes = sum(1 for p in root.findall("programme") if p.get("channel") == CHANNEL_ID)
    if programmes == 0:
        raise ValueError("Pikaboo has 0 Telemach programmes")

    source_logo = telemach_logo(config_path)
    download_png(source_logo, logos_dir / "telemach-921.png")

    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": RAW_LOGO})

    names = {(n.text or "").strip() for n in channel.findall("display-name")}
    if "PIKABOO" not in names:
        ET.SubElement(channel, "display-name").text = "PIKABOO"

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Pikaboo.ba: {programmes} programmes; logo={RAW_LOGO}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: import_pikaboo_telemach.py guide.xml telemach.config.js logos_dir")
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
