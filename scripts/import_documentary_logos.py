#!/usr/bin/env python3
"""Host selected Telemach channel logos alongside the published XMLTV guide."""

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


CHANNELS = {
    "1855": "slovnationalgeographic.si",
    "1863": "natgeowild.ba",
    "1830": "animal_planet",
    "1478": "discovery.dk",
    "1857": "historychannel2.ba",
    "1861": "276770344357",
    "1640": "iptv#ch-bbc-earth-hd",
    "1867": "eentertainment.ba",
    "1866": "travelchannel.bh",
    "1860": "loviribolov.ba",
    "1858": "435380776371",  # Viasat History
    "1862": "276767784232",  # Viasat Nature
    "119": "iptv#ch-127-tlc",  # TLC
    "1864": "276771368119",  # Crime & Investigation
    "1120": "276770856271",  # Da Vinci
    "1865": "iptv#ch-444-hgtv",  # Home and Garden TV
}
IMAGE_HOST = "images-web.ug-be.cdn.united.cloud"
BASE_URL = f"https://{IMAGE_HOST}"
REPO_URL = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"


def json_request(url, headers, data=None):
    with urlopen(Request(url, headers=headers, data=data), timeout=30) as response:
        return json.load(response)


def image_for(channel):
    images = channel.get("images") or []
    if not isinstance(images, list):
        images = []
    candidates = [item for item in images if isinstance(item, dict) and item.get("path")]
    candidates.sort(key=lambda item: ("LOGO" not in str(item.get("type", "")).upper(),
                                      "LOGO" not in str(item.get("legacyType", "")).upper()))
    if not candidates:
        raise ValueError(f"No logo image on Telemach channel {channel.get('id')}: keys={list(channel)}")
    path = candidates[0]["path"]
    url = urljoin(BASE_URL, path)
    if urlparse(url).hostname != IMAGE_HOST:
        raise ValueError(f"Unexpected channel image host for {channel.get('id')}")
    return url


def extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    raise ValueError("Unrecognized downloaded channel logo format")


def main(config, csv_path, logos_dir):
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["guide_id", "logo_url"]:
            raise ValueError("Unexpected logo CSV header")
        rows = list(reader)
    configured = {row["guide_id"]: row for row in rows}
    if set(CHANNELS.values()) - set(configured):
        raise ValueError("Missing documentary channel logo mappings")

    # Once imported, these local files remain usable even if the source API is unavailable.
    if all(configured[guide_id]["logo_url"].startswith(REPO_URL + f"telemach-{site_id}.")
           and (logos_dir / configured[guide_id]["logo_url"].removeprefix(REPO_URL)).is_file()
           for site_id, guide_id in CHANNELS.items()):
        print(f"All {len(CHANNELS)} Telemach logos are already hosted in this repository")
        return

    script = config.read_text(encoding="utf-8")
    match = re.search(r"const BASIC_TOKEN\s*=\s*'([^']+)'", script)
    if not match:
        raise ValueError("Telemach grabber authentication configuration changed upstream")

    token = json_request(
        "https://api-web.ug-be.cdn.united.cloud/oauth/token?grant_type=client_credentials",
        {"Authorization": f"Basic {match.group(1)}"}, data=b"{}"
    )["access_token"]
    channels = json_request(
        "https://api-web.ug-be.cdn.united.cloud/v1/public/channels"
        "?channelType=TV&communityId=12&languageId=59&imageSize=L",
        {"Authorization": f"Bearer {token}"}
    )
    by_id = {str(channel["id"]): channel for channel in channels}
    if set(CHANNELS) - set(by_id):
        raise ValueError(f"Missing Telemach channels: {sorted(set(CHANNELS) - set(by_id))}")

    downloads = {}
    for site_id, guide_id in CHANNELS.items():
        url = image_for(by_id[site_id])
        with urlopen(Request(url, headers={"Referer": "https://epg.telemach.ba/"}), timeout=30) as response:
            data = response.read(2_000_001)
        if not data or len(data) > 2_000_000:
            raise ValueError(f"Empty or oversized Telemach channel logo: {site_id}")
        filename = f"telemach-{site_id}.{extension(data)}"
        downloads[site_id] = (guide_id, filename, data)
        print(f"Found Telemach logo: {site_id} {by_id[site_id].get('name')} {filename} ({len(data)} bytes)")

    logos_dir.mkdir(parents=True, exist_ok=True)
    for guide_id, filename, data in downloads.values():
        (logos_dir / filename).write_bytes(data)
        configured[guide_id]["logo_url"] = REPO_URL + filename

    with csv_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Imported {len(CHANNELS)} official Telemach logos into logos/ and updated logo mappings")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: import_documentary_logos.py <telemach.config.js> <logos.csv> <logos_dir>")
    main(*(Path(arg) for arg in sys.argv[1:]))
