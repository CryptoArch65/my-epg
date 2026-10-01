#!/usr/bin/env python3
"""Isolated MTS v2 test for TV Krusevac.

Uses the same v2 product-search endpoint as the current mts.rs website and
interprets the programme clock as Europe/Belgrade wall time. Only TV Krusevac
(and its known XMLTV aliases) is replaced; all other channels are untouched.
"""

import copy
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Belgrade")
API = "https://mts.rs/hybris/mtscommercewebservices/v2/mtsB2C/products/search"
GUIDE_ID = "TVKrusevac.rs"
ALIASES = ("TV Kruševac", "tv_krusevac")
CODE = "tv_krusevac"
DISPLAY = "TV Kruševac"


def fetch(day, page=0):
    # Same search context/category/date family used by the live MTS website.
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 50,
        "fields": "FULL",
        "currentPage": page,
    })
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    })
    with urlopen(req, timeout=35) as response:
        return json.load(response)


def products_for_day(day):
    first = fetch(day, 0)
    pagination = first.get("pagination") or {}
    pages = pagination.get("totalPages", 1)
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS v2 pagination: {pagination!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        data = fetch(day, page)
        products.extend(data.get("products") or [])
    print(f"MTS v2 {day}: {len(products)} products across {pages} pages")
    return products


def local_stamp(value):
    """MTS v2 labels wall-clock values +0000, while the website displays them locally.

    Example from the live website/API on 2026-10-01:
    13:15+0000 is displayed by mts.rs as 13:15 in Serbia. For this isolated test,
    preserve the wall-clock value and attach Europe/Belgrade explicitly.
    """
    if not isinstance(value, str) or len(value) < 19:
        raise ValueError(f"Unexpected MTS v2 timestamp: {value!r}")
    dt = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE)
    return dt.strftime("%Y%m%d%H%M%S %z")


def product_logo(product):
    for image in product.get("images") or []:
        if isinstance(image, dict) and image.get("imageType") == "PRIMARY" and image.get("url"):
            return image["url"]
    return None


def add_programme(root, channel_id, item):
    start = local_stamp(item["start"])
    stop = local_stamp(item["end"])
    if start >= stop:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    programme = ET.SubElement(root, "programme", channel=channel_id, start=start, stop=stop)
    ET.SubElement(programme, "title", lang="sr").text = title
    description = item.get("description")
    if isinstance(description, str) and description.strip():
        ET.SubElement(programme, "desc", lang="sr").text = description.strip()
    category = item.get("category")
    if isinstance(category, str) and category.strip():
        ET.SubElement(programme, "category", lang="sr").text = category.strip()
    picture = item.get("picture")
    if isinstance(picture, dict) and picture.get("url"):
        ET.SubElement(programme, "image").text = picture["url"]
    return programme


def ensure_alias(root, source_channel, alias_id):
    channels = {c.get("id"): c for c in root.findall("channel")}
    alias = channels.get(alias_id)
    if alias is None:
        alias = copy.deepcopy(source_channel)
        alias.set("id", alias_id)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source_channel:
            alias.append(copy.deepcopy(child))


def main(path):
    today = datetime.now(ZONE).date()
    items = []
    sample = None
    for day in (today, today + timedelta(days=1)):
        products = products_for_day(day.isoformat())
        product = next((p for p in products if p.get("code") == CODE), None)
        if product is None:
            raise ValueError(f"TV Krusevac ({CODE}) not found in MTS v2 on {day}")
        sample = sample or product
        items.extend(product.get("programs") or [])

    tree = ET.parse(path)
    root = tree.getroot()
    channels = {c.get("id"): c for c in root.findall("channel")}
    channel = channels.get(GUIDE_ID)
    if channel is None:
        channel = ET.Element("channel", {"id": GUIDE_ID})
        ET.SubElement(channel, "display-name", {"lang": "sr"}).text = DISPLAY
        root.insert(len(root.findall("channel")), channel)

    logo = product_logo(sample or {})
    if logo:
        for icon in list(channel.findall("icon")):
            channel.remove(icon)
        ET.SubElement(channel, "icon", {"src": logo})

    ids = {GUIDE_ID, *ALIASES, CODE}
    for programme in list(root.findall("programme")):
        if programme.get("channel") in ids:
            root.remove(programme)

    added = 0
    for item in items:
        if add_programme(root, GUIDE_ID, item) is not None:
            added += 1
    if added == 0:
        raise ValueError("MTS v2 TV Krusevac returned 0 usable programmes")

    # Mirror the tested schedule onto the IDs TiviMate/provider mappings may use.
    source_programmes = [p for p in root.findall("programme") if p.get("channel") == GUIDE_ID]
    for alias_id in ALIASES:
        ensure_alias(root, channel, alias_id)
        for p in source_programmes:
            clone = copy.deepcopy(p)
            clone.set("channel", alias_id)
            root.append(clone)

    tree.write(path, encoding="utf-8", xml_declaration=True)

    # Diagnostic: print today's v2 schedule around the current Serbian time.
    now = datetime.now(ZONE)
    todays = []
    for item in items:
        try:
            start = datetime.strptime(item["start"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE)
            stop = datetime.strptime(item["end"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE)
        except Exception:
            continue
        if start.date() == today:
            todays.append((start, stop, item.get("title", "")))
    print(f"MTS v2 TV Krusevac: {added} programmes, logo={'yes' if logo else 'no'}")
    for start, stop, title in sorted(todays):
        if stop >= now - timedelta(hours=2) and start <= now + timedelta(hours=3):
            print(f"  {start:%H:%M}-{stop:%H:%M} {title}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: test_mts_v2_krusevac.py guide.xml")
    main(Path(sys.argv[1]))
