#!/usr/bin/env python3
"""Supplement Serbian EPG entries that need special MTS/alias handling.

- K1: keep the existing guide schedule, then fill uncovered gaps with programmes
  from every MTS API page (checking both K1 product codes).
- Balkan Trip: expose the already-working m:tel schedule under the provider's
  ``Balkan Trip`` tvg-id as well as its canonical guide id.
"""

import copy
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

from import_mts_pink_epg import ZONE, day_products, stamp

K1_ID = "K1.rs"
K1_ALIASES = ("k1-tv", "k1_duplicate")
K1_CODES = ("k1_hd", "k1_duplicate")

BALKAN_SOURCE_ID = "iptv#ch-461-balkan-trip-hd"
BALKAN_ALIAS_ID = "Balkan Trip"


def parse_xmltv_time(value):
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def programme_interval(programme):
    try:
        return parse_xmltv_time(programme.get("start")), parse_xmltv_time(programme.get("stop"))
    except (TypeError, ValueError):
        return None


def overlaps(start, stop, intervals):
    return any(start < other_stop and other_start < stop for other_start, other_stop in intervals)


def add_item(root, channel_id, start, stop, item):
    programme = ET.SubElement(root, "programme", channel=channel_id, start=start, stop=stop)
    ET.SubElement(programme, "title", lang="sr").text = item["title"].strip()

    description = item.get("description")
    if isinstance(description, str) and description.strip():
        ET.SubElement(programme, "desc", lang="sr").text = description.strip()

    category = item.get("category")
    if isinstance(category, str) and category.strip():
        ET.SubElement(programme, "category", lang="sr").text = category.strip()
    elif isinstance(category, list):
        for value in category:
            if isinstance(value, str) and value.strip():
                ET.SubElement(programme, "category", lang="sr").text = value.strip()

    picture = item.get("picture")
    if isinstance(picture, dict):
        image = picture.get("url")
        if isinstance(image, str) and image.strip():
            ET.SubElement(programme, "image").text = image.strip()

    return programme


def supplement_k1(root):
    channels = {channel.get("id") for channel in root.findall("channel")}
    if K1_ID not in channels:
        print(f"WARNING: {K1_ID} is missing; cannot supplement K1")
        return 0

    today = datetime.now(ZONE).date()
    candidates = []
    seen = set()
    per_code = {code: 0 for code in K1_CODES}

    try:
        for day in (today, today + timedelta(days=1)):
            products = day_products(day.isoformat())
            by_code = {product.get("code"): product for product in products}
            for code in K1_CODES:
                product = by_code.get(code)
                if product is None:
                    continue
                for item in product.get("programs") or []:
                    title = item.get("title")
                    if not isinstance(title, str) or not title.strip():
                        continue
                    try:
                        start = stamp(item["start"])
                        stop = stamp(item["end"])
                        start_dt = parse_xmltv_time(start)
                        stop_dt = parse_xmltv_time(stop)
                    except (KeyError, TypeError, ValueError) as exc:
                        print(f"WARNING: skipping malformed K1 MTS item: {exc}")
                        continue
                    if start_dt >= stop_dt:
                        continue
                    key = (start, stop, title.strip())
                    if key in seen:
                        continue
                    seen.add(key)
                    per_code[code] += 1
                    candidates.append((start_dt, stop_dt, start, stop, item, code))
    except Exception as exc:
        print(f"WARNING: MTS K1 supplement unavailable; keeping existing K1 schedule: {exc}")
        return 0

    existing = [p for p in root.findall("programme") if p.get("channel") == K1_ID]
    intervals = []
    for programme in existing:
        interval = programme_interval(programme)
        if interval is not None:
            intervals.append(interval)

    aliases = [alias for alias in K1_ALIASES if alias in channels]
    added = 0
    for start_dt, stop_dt, start, stop, item, code in sorted(candidates, key=lambda row: (row[0], K1_CODES.index(row[5]))):
        if overlaps(start_dt, stop_dt, intervals):
            continue

        programme = add_item(root, K1_ID, start, stop, item)
        for alias in aliases:
            alias_programme = copy.deepcopy(programme)
            alias_programme.set("channel", alias)
            root.append(alias_programme)

        intervals.append((start_dt, stop_dt))
        added += 1

    print(
        "K1 MTS supplement: "
        f"existing={len(existing)}, "
        f"mts_k1_hd={per_code['k1_hd']}, "
        f"mts_k1_duplicate={per_code['k1_duplicate']}, "
        f"gap_fill_added={added}, aliases={','.join(aliases) or 'none'}"
    )

    now = datetime.now(ZONE)
    current = 0
    for programme in root.findall("programme"):
        if programme.get("channel") != K1_ID:
            continue
        interval = programme_interval(programme)
        if interval is not None and interval[0] <= now < interval[1]:
            current += 1
    print(f"K1 current programme coverage after supplement: {current}")
    return added


def sync_balkan_alias(root):
    channels = {channel.get("id"): channel for channel in root.findall("channel")}
    source = channels.get(BALKAN_SOURCE_ID)
    if source is None:
        print(f"WARNING: Balkan Trip source {BALKAN_SOURCE_ID} is missing")
        return 0

    alias = channels.get(BALKAN_ALIAS_ID)
    if alias is None:
        alias = copy.deepcopy(source)
        alias.set("id", BALKAN_ALIAS_ID)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source:
            alias.append(copy.deepcopy(child))

    names = [node.text for node in alias.findall("display-name")]
    if "|SRB| BALKAN TRIP" not in names:
        ET.SubElement(alias, "display-name", lang="sr").text = "|SRB| BALKAN TRIP"

    for programme in list(root.findall("programme")):
        if programme.get("channel") == BALKAN_ALIAS_ID:
            root.remove(programme)

    source_programmes = [
        programme for programme in root.findall("programme")
        if programme.get("channel") == BALKAN_SOURCE_ID
    ]
    for programme in source_programmes:
        alias_programme = copy.deepcopy(programme)
        alias_programme.set("channel", BALKAN_ALIAS_ID)
        root.append(alias_programme)

    print(f"Balkan Trip alias {BALKAN_ALIAS_ID}: {len(source_programmes)} programmes copied from {BALKAN_SOURCE_ID}")
    return len(source_programmes)


def main(guide_path):
    tree = ET.parse(guide_path)
    root = tree.getroot()

    supplement_k1(root)
    sync_balkan_alias(root)

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_serbia_epg.py guide.xml")
    main(Path(sys.argv[1]))
