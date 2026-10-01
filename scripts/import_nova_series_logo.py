#!/usr/bin/env python3
"""Set Nova Series logo with MTS priority and expose useful XMLTV aliases."""

import copy
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from import_mts_pink_epg import day_products

CHANNEL_ID = "NovaSeries.rs"
SITE_ID = "1604"
ALIASES = ("Nova Series", "NovaSeries", "nova_series", "nova-series", "novaseries.rs")
ZONE = ZoneInfo("Europe/Belgrade")
IMAGE_HOST = "images-web.ug-be.cdn.united.cloud"


def norm(value):
    value = str(value or "").casefold()
    value = value.replace("š", "s").replace("đ", "dj").replace("č", "c").replace("ć", "c").replace("ž", "z")
    return re.sub(r"[^a-z0-9]+", "", value)


def first_url(value, base=""):
    if isinstance(value, str):
        if value.startswith("https://"):
            return value
        if base and value.startswith("/"):
            return urljoin(base, value)
        return None
    if isinstance(value, list):
        for item in value:
            url = first_url(item, base)
            if url:
                return url
    if isinstance(value, dict):
        for key in ("url", "src", "path", "image", "logo"):
            if key in value:
                url = first_url(value[key], base)
                if url:
                    return url
        for item in value.values():
            url = first_url(item, base)
            if url:
                return url
    return None


def mts_logo():
    products = day_products(datetime.now(ZONE).date().isoformat())
    for product in products:
        name = product.get("name") or product.get("title") or product.get("channelName")
        if norm(name) not in {"novaseries", "novaserieshd"}:
            continue
        logo = (
            first_url(product.get("picture"), "https://mts.rs")
            or first_url(product.get("images"), "https://mts.rs")
            or first_url(product.get("logo"), "https://mts.rs")
        )
        if logo and urlparse(logo).hostname in {
            "mts.rs", "www.mts.rs", "medias.services.mts.rs", "mediasb2c.mts.rs"
        }:
            print(f"Nova Series logo source: MTS ({product.get('code')})")
            return logo
    return None


def json_request(url, headers, data=None):
    with urlopen(Request(url, headers=headers, data=data), timeout=30) as response:
        return json.load(response)


def telemach_logo(config_path):
    script = config_path.read_text(encoding="utf-8")
    match = re.search(r"const BASIC_TOKEN\s*=\s*'([^']+)'", script)
    if not match:
        raise ValueError("Telemach auth token not found in upstream config")
    token = json_request(
        "https://api-web.ug-be.cdn.united.cloud/oauth/token?grant_type=client_credentials",
        {"Authorization": f"Basic {match.group(1)}"},
        data=b"{}",
    )["access_token"]
    channels = json_request(
        "https://api-web.ug-be.cdn.united.cloud/v1/public/channels"
        "?channelType=TV&communityId=12&languageId=59&imageSize=L",
        {"Authorization": f"Bearer {token}"},
    )
    channel = next((item for item in channels if str(item.get("id")) == SITE_ID), None)
    if channel is None:
        raise ValueError("Nova Series missing from Telemach channel catalogue")
    images = channel.get("images") or []
    candidates = [item for item in images if isinstance(item, dict) and item.get("path")]
    candidates.sort(key=lambda item: (
        "LOGO" not in str(item.get("type", "")).upper(),
        "LOGO" not in str(item.get("legacyType", "")).upper(),
    ))
    if not candidates:
        raise ValueError("Telemach Nova Series has no logo image")
    logo = urljoin(f"https://{IMAGE_HOST}", candidates[0]["path"])
    print("Nova Series logo source: Telemach fallback")
    return logo


def sync_alias(root, source_id, alias_id):
    channels = {node.get("id"): node for node in root.findall("channel")}
    source = channels[source_id]
    alias = channels.get(alias_id)
    if alias is None:
        alias = copy.deepcopy(source)
        alias.set("id", alias_id)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source:
            alias.append(copy.deepcopy(child))

    for programme in list(root.findall("programme")):
        if programme.get("channel") == alias_id:
            root.remove(programme)
    for programme in root.findall("programme"):
        if programme.get("channel") == source_id:
            clone = copy.deepcopy(programme)
            clone.set("channel", alias_id)
            root.append(clone)


def main(guide_path, telemach_config):
    tree = ET.parse(guide_path)
    root = tree.getroot()
    channels = {node.get("id"): node for node in root.findall("channel")}
    channel = channels.get(CHANNEL_ID)
    if channel is None:
        raise ValueError(f"Missing {CHANNEL_ID} after Telemach grab")

    names = [node.text for node in channel.findall("display-name")]
    if "|SRB| NOVA SERIES" not in names:
        ET.SubElement(channel, "display-name", lang="sr").text = "|SRB| NOVA SERIES"

    logo = None
    try:
        logo = mts_logo()
    except Exception as exc:
        print(f"WARNING: MTS Nova Series logo lookup failed: {exc}")
    if not logo:
        logo = telemach_logo(telemach_config)

    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": logo})

    for alias in ALIASES:
        sync_alias(root, CHANNEL_ID, alias)

    count = sum(1 for p in root.findall("programme") if p.get("channel") == CHANNEL_ID)
    if count == 0:
        raise ValueError("Nova Series has no Telemach programmes")

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Nova Series: {count} programmes; aliases={','.join(ALIASES)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_nova_series_logo.py guide.xml telemach.config.js")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
