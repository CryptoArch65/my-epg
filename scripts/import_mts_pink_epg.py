#!/usr/bin/env python3
"""Import Pink schedules from every page of the MTS channel API."""

import csv
import json
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Belgrade")
API = "https://mts.rs/hybris/ecommerce/b2c/v1/products/search"


def fetch(day, page):
    query = ":pozicija-rastuce:tip-kanala-radio:TV kanali:channelProgramDates:" + day
    url = API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 10000,
        "currentPage": page,
    })
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=35) as response:
        return json.load(response)


def day_products(day):
    first = fetch(day, 0)
    pagination = first.get("pagination") or {}
    pages = pagination.get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 30 or not isinstance(first.get("products"), list):
        raise ValueError(f"Unexpected MTS pagination on {day}: {pagination!r}")
    products = list(first["products"])
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch, day, page): page for page in range(1, pages)}
        for job in as_completed(jobs):
            data = job.result()
            if not isinstance(data.get("products"), list) or data.get("pagination", {}).get("currentPage") != jobs[job]:
                raise ValueError(f"Incomplete MTS page {jobs[job]} on {day}")
            products.extend(data["products"])
    print(f"MTS {day}: read {len(products)} products across {pages} pages")
    return products


def stamp(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000 if value > 10**11 else value, ZONE)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"Unexpected MTS timestamp: {value!r}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZONE)
    return value.strftime("%Y%m%d%H%M%S %z")


def main(guide_path, mapping_path):
    with mapping_path.open(newline="", encoding="utf-8") as source:
        mappings = list(csv.DictReader(source))
    if not mappings or any(set(row) != {"guide_id", "mts_site_id", "channel_name"} for row in mappings):
        raise ValueError("Invalid Pink MTS mapping")
    by_code = {unquote(row["mts_site_id"]): row["guide_id"] for row in mappings}
    if len(by_code) != len(mappings):
        raise ValueError("Duplicate MTS code in Pink mapping")
    today = datetime.now(ZONE).date()
    schedules = {row["guide_id"]: {} for row in mappings}
    for day in (today, today + timedelta(days=1)):
        for product in day_products(day.isoformat()):
            guide_id = by_code.get(product.get("code"))
            if guide_id is None:
                continue
            for item in product.get("programs") or []:
                title = item.get("title")
                if not isinstance(title, str) or not title.strip():
                    continue
                start, stop = stamp(item["start"]), stamp(item["end"])
                if start >= stop:
                    continue
                schedules[guide_id][(start, stop, title)] = item

    tree = ET.parse(guide_path)
    root = tree.getroot()
    available = {channel.get("id") for channel in root.findall("channel")}
    missing = set(schedules) - available
    if missing:
        raise ValueError(f"MTS Pink guide channels missing: {sorted(missing)}")
    active = {guide_id: items for guide_id, items in schedules.items() if items}
    for programme in list(root.findall("programme")):
        if programme.get("channel") in active:
            root.remove(programme)
    for guide_id, items in active.items():
        for (start, stop, title), item in sorted(items.items()):
            programme = ET.SubElement(root, "programme", channel=guide_id, start=start, stop=stop)
            ET.SubElement(programme, "title", lang="bs").text = title
            description = item.get("description")
            if isinstance(description, str) and description.strip():
                ET.SubElement(programme, "desc", lang="bs").text = description
        print(f"MTS Pink {guide_id}: {len(items)} programmes")
    unavailable = sorted(set(schedules) - set(active))
    print(f"MTS Pink: {len(active)}/{len(schedules)} channels with schedules; unavailable: {', '.join(unavailable)}")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_mts_pink_epg.py guide.xml pink-mts-channels.csv")
    main(*(Path(value) for value in sys.argv[1:]))
