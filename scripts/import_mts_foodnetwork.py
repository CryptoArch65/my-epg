#!/usr/bin/env python3
"""Import Food Network EPG from the live MTS v2 feed and mirror it to the provider ID."""

from __future__ import annotations

import copy
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

MTS_API = "https://mts.rs/hybris/mtscommercewebservices/v2/mtsB2C/products/search"
TZ = ZoneInfo("Europe/Belgrade")
CODE = "food_network_hd"
TARGET_IDS = ("iptv#ch-451-food-network", "foodnetwork.ba")


def fetch_page(day: str, page: int) -> dict:
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = MTS_API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 50,
        "fields": "FULL",
        "currentPage": page,
    })
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def products_for_day(day: str) -> list[dict]:
    first = fetch_page(day, 0)
    pages = (first.get("pagination") or {}).get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS pagination: {first.get('pagination')!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        products.extend(fetch_page(day, page).get("products") or [])
    return products


def local_time(value: str) -> datetime:
    return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TZ)


def ensure_channel(root: ET.Element, channel_id: str, names: tuple[str, ...]) -> ET.Element:
    channel = next((c for c in root.findall("channel") if c.get("id") == channel_id), None)
    if channel is None:
        channel = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), channel)
    existing = {(n.text or "").strip() for n in channel.findall("display-name")}
    for name in names:
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = name
    return channel


def add_programme(root: ET.Element, channel_id: str, item: dict) -> ET.Element | None:
    try:
        start = local_time(item["start"])
        stop = local_time(item["end"])
    except Exception:
        return None
    title = str(item.get("title") or "").strip()
    if not title or stop <= start:
        return None
    p = ET.SubElement(root, "programme", {
        "channel": channel_id,
        "start": start.strftime("%Y%m%d%H%M%S %z"),
        "stop": stop.strftime("%Y%m%d%H%M%S %z"),
    })
    ET.SubElement(p, "title", {"lang": "sr"}).text = title
    desc = str(item.get("description") or "").strip()
    if desc:
        ET.SubElement(p, "desc", {"lang": "sr"}).text = desc
    category = str(item.get("category") or "").strip()
    if category:
        ET.SubElement(p, "category", {"lang": "sr"}).text = category
    picture = item.get("picture")
    if isinstance(picture, dict) and picture.get("url"):
        ET.SubElement(p, "image").text = str(picture["url"])
    return p


def main(path: Path) -> None:
    today = datetime.now(TZ).date()
    items = []
    source_name = ""
    for day in (today, today + timedelta(days=1)):
        product = next((p for p in products_for_day(day.isoformat()) if str(p.get("code") or "") == CODE), None)
        if product is None:
            print(f"WARNING: MTS {CODE} missing for {day}")
            continue
        source_name = source_name or str(product.get("name") or "")
        items.extend(product.get("programs") or [])

    seen = set()
    usable = []
    for item in items:
        try:
            key = (local_time(item["start"]), local_time(item["end"]), str(item.get("title") or "").strip())
        except Exception:
            continue
        if not key[2] or key[1] <= key[0] or key in seen:
            continue
        seen.add(key)
        usable.append(item)
    usable.sort(key=lambda item: local_time(item["start"]))
    if len(usable) < 10:
        raise SystemExit(f"MTS Food Network only has {len(usable)} current programmes")

    tree = ET.parse(path)
    root = tree.getroot()
    source = ensure_channel(root, TARGET_IDS[0], ("Food Network", "FOOD NETWORK"))
    alias = ensure_channel(root, TARGET_IDS[1], ("FOOD NETWORK", "Food Network"))

    target_ids = set(TARGET_IDS)
    for node in list(root.findall("programme")):
        if node.get("channel") in target_ids:
            root.remove(node)

    source_nodes = []
    for item in usable:
        node = add_programme(root, TARGET_IDS[0], item)
        if node is not None:
            source_nodes.append(node)
    for node in source_nodes:
        clone = copy.deepcopy(node)
        clone.set("channel", TARGET_IDS[1])
        root.append(clone)

    # Keep whichever existing source/provider logo is already configured.
    if alias.find("icon") is None and source.find("icon") is not None:
        alias.append(copy.deepcopy(source.find("icon")))

    described = sum(1 for item in usable if str(item.get("description") or "").strip())
    print(f"Food Network from MTS: code={CODE!r}, name={source_name!r}, programmes={len(source_nodes)}, descriptions={described}/{len(usable)}, ids={TARGET_IDS}")

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_foodnetwork.py guide.xml")
    main(Path(sys.argv[1]))
