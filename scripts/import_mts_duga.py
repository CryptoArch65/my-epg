#!/usr/bin/env python3
"""Fill Duga TV from the live MTS v2 website feed when the legacy grabber is empty."""

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
CHANNEL_ID = "DugaTV.rs"
MTS_CODE = "tv_duga_plus"


def fetch_page(day, page):
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 50,
        "fields": "FULL",
        "currentPage": page,
    })
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    })
    with urlopen(request, timeout=40) as response:
        return json.load(response)


def products_for_day(day):
    first = fetch_page(day, 0)
    pages = (first.get("pagination") or {}).get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS pagination: {first.get('pagination')!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        products.extend(fetch_page(day, page).get("products") or [])
    return products


def stamp(value):
    if not isinstance(value, str) or len(value) < 19:
        raise ValueError(value)
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE).strftime("%Y%m%d%H%M%S %z")


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        print("Duga TV channel is not present in this XML; nothing to do")
        return

    today = datetime.now(ZONE).date()
    items = []
    product_name = ""
    for day in (today, today + timedelta(days=1)):
        products = products_for_day(day.isoformat())
        product = next((p for p in products if str(p.get("code") or "") == MTS_CODE), None)
        if product:
            product_name = product_name or str(product.get("name") or "")
            items.extend(product.get("programs") or [])

    usable = []
    seen = set()
    for item in items:
        try:
            key = (stamp(item["start"]), stamp(item["end"]), str(item.get("title") or "").strip())
        except Exception:
            continue
        if not key[2] or key in seen:
            continue
        seen.add(key)
        usable.append(item)

    if not usable:
        print(f"MTS v2 Duga TV: no usable programmes for code={MTS_CODE!r}")
        return

    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)

    for item in usable:
        programme = ET.SubElement(root, "programme", channel=CHANNEL_ID, start=stamp(item["start"]), stop=stamp(item["end"]))
        ET.SubElement(programme, "title", lang="sr").text = str(item.get("title") or "").strip()
        desc = item.get("description")
        if isinstance(desc, str) and desc.strip():
            ET.SubElement(programme, "desc", lang="sr").text = desc.strip()
        category = item.get("category")
        if isinstance(category, str) and category.strip():
            ET.SubElement(programme, "category", lang="sr").text = category.strip()

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"MTS v2 Duga TV: name={product_name!r}, programmes={len(usable)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_duga.py XMLTV.xml")
    main(Path(sys.argv[1]))
