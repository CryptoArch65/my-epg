#!/usr/bin/env python3
"""Import Superstar TV 1/2/3 schedules from the live MTS v2 feed.

The official Superstar website schedule is currently stale. This importer only
replaces the guide schedules when the MTS feed is current and has useful
programme descriptions, then mirrors the canonical schedules onto active
playlist aliases already present in guide.xml.
"""

from __future__ import annotations

import copy
import csv
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
PLAYLIST_ALIASES = Path("config/playlist_aliases.csv")
MIN_DESC_COVERAGE = 0.50

TARGETS = {
    "SuperstarTV1.rs": {
        "codes": ("superstar_tv_hd", "superstar_tv"),
        "display_names": ("SUPERSTAR TV HD", "SUPERSTAR TV", "SUPERSTAR TV ᴴᴰ"),
    },
    "SuperstarTV2.rs": {
        "codes": ("superstar_2_hd",),
        "display_names": ("SUPERSTAR TV 2", "SUPERSTAR 2"),
    },
    "SuperstarTV3.rs": {
        "codes": ("Superstar_3",),
        "display_names": ("SUPERSTAR TV 3", "SUPERSTAR 3"),
    },
}


def fetch_page(day: str, page: int) -> dict:
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = MTS_API + "?" + urlencode(
        {
            "sort": "pozicija-rastuce",
            "searchQueryContext": "CHANNEL_PROGRAM",
            "query": query,
            "pageSize": 50,
            "fields": "FULL",
            "currentPage": page,
        }
    )
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(request, timeout=40) as response:
        return json.load(response)


def fetch_products(day: str) -> list[dict]:
    first = fetch_page(day, 0)
    pages = (first.get("pagination") or {}).get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS pagination: {first.get('pagination')!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        products.extend(fetch_page(day, page).get("products") or [])
    print(f"MTS {day}: {len(products)} products across {pages} pages")
    return products


def local_time(value: str) -> datetime:
    # MTS v2 labels timestamps +0000 but displays the clock portion as Serbian
    # local wall time. Keep the same tested convention as the repo's v2 importer.
    return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TZ)


def valid_programmes(items: list[dict]) -> list[dict]:
    rows = []
    seen = set()
    for item in items:
        try:
            start = local_time(item["start"])
            stop = local_time(item["end"])
        except Exception:
            continue
        title = str(item.get("title") or "").strip()
        if not title or stop <= start:
            continue
        key = (start, stop, title)
        if key in seen:
            continue
        seen.add(key)
        rows.append(item)
    return rows


def description_coverage(items: list[dict]) -> tuple[int, int, float]:
    total = len(items)
    described = sum(1 for item in items if str(item.get("description") or "").strip())
    return described, total, (described / total if total else 0.0)


def find_best_product(products_by_day: dict, codes: tuple[str, ...]) -> tuple[str, str, list[dict]]:
    candidates = []
    for code in codes:
        combined = []
        source_name = ""
        for products in products_by_day.values():
            product = next((p for p in products if str(p.get("code") or "") == code), None)
            if product is None:
                continue
            source_name = source_name or str(product.get("name") or "")
            combined.extend(product.get("programs") or [])
        rows = valid_programmes(combined)
        described, total, coverage = description_coverage(rows)
        candidates.append((total, coverage, described, code, source_name, rows))
        print(
            f"MTS candidate {code}: name={source_name!r}, programmes={total}, "
            f"descriptions={described}/{total} ({coverage:.0%})"
        )
    candidates.sort(reverse=True, key=lambda row: (row[0], row[1]))
    if not candidates or candidates[0][0] == 0:
        raise ValueError(f"No MTS programme data for candidates {codes!r}")
    _, _, _, code, source_name, rows = candidates[0]
    return code, source_name, rows


def ensure_names(channel: ET.Element, names: tuple[str, ...]) -> None:
    existing = {(node.text or "").strip() for node in channel.findall("display-name")}
    for name in names:
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = name


def aliases_for(guide_id: str, root: ET.Element) -> list[str]:
    existing_channels = {c.get("id") for c in root.findall("channel")}
    aliases = []
    if not PLAYLIST_ALIASES.exists():
        return aliases
    with PLAYLIST_ALIASES.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if (row.get("guide_id") or "").strip() != guide_id:
                continue
            alias = (row.get("playlist_tvg_id") or "").strip()
            if alias and alias != guide_id and alias in existing_channels:
                aliases.append(alias)
    return sorted(set(aliases))


def add_programme(root: ET.Element, channel_id: str, item: dict) -> ET.Element:
    start = local_time(item["start"])
    stop = local_time(item["end"])
    programme = ET.SubElement(
        root,
        "programme",
        {
            "channel": channel_id,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        },
    )
    ET.SubElement(programme, "title", {"lang": "sr"}).text = str(item.get("title") or "").strip()
    description = str(item.get("description") or "").strip()
    if description:
        ET.SubElement(programme, "desc", {"lang": "sr"}).text = description
    category = str(item.get("category") or "").strip()
    if category:
        ET.SubElement(programme, "category", {"lang": "sr"}).text = category
    picture = item.get("picture")
    if isinstance(picture, dict) and picture.get("url"):
        ET.SubElement(programme, "image").text = str(picture["url"])
    return programme


def replace_schedule(root: ET.Element, guide_id: str, aliases: list[str], items: list[dict]) -> int:
    target_ids = {guide_id, *aliases}
    for node in list(root.findall("programme")):
        if node.get("channel") in target_ids:
            root.remove(node)

    source_nodes = [add_programme(root, guide_id, item) for item in items]
    for alias in aliases:
        for source in source_nodes:
            clone = copy.deepcopy(source)
            clone.set("channel", alias)
            root.append(clone)
    return len(source_nodes)


def main(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    channels = {c.get("id"): c for c in root.findall("channel")}

    today = datetime.now(TZ).date()
    days = (today, today + timedelta(days=1))
    products_by_day = {day: fetch_products(day.isoformat()) for day in days}

    for guide_id, spec in TARGETS.items():
        channel = channels.get(guide_id)
        if channel is None:
            raise SystemExit(f"Missing canonical guide channel {guide_id}")

        code, source_name, items = find_best_product(products_by_day, spec["codes"])
        described, total, coverage = description_coverage(items)
        if total < 10:
            raise SystemExit(f"MTS {guide_id} only has {total} current programmes")
        if coverage < MIN_DESC_COVERAGE:
            raise SystemExit(
                f"MTS {guide_id} description coverage too low: {described}/{total} ({coverage:.0%}); "
                "keeping existing guide unchanged"
            )

        ensure_names(channel, spec["display_names"])
        aliases = aliases_for(guide_id, root)
        written = replace_schedule(root, guide_id, aliases, items)

        samples = []
        for item in items:
            description = str(item.get("description") or "").strip()
            if description:
                samples.append(f"{str(item.get('title') or '').strip()}: {description[:120]}")
            if len(samples) == 2:
                break
        print(
            f"MTS {guide_id}: selected={code!r} name={source_name!r}, programmes={written}, "
            f"descriptions={described}/{total} ({coverage:.0%}), aliases={aliases}"
        )
        for sample in samples:
            print(f"  description sample: {sample}")

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_superstar.py guide.xml")
    main(Path(sys.argv[1]))
