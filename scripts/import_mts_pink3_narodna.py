#!/usr/bin/env python3
"""Import PINK 3 VESTI and NARODNA TV EPG + logos from the live MTS v2 feed."""

from __future__ import annotations

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

TARGETS = {
    "vesti.rs": {
        "code": "vesti",
        "display_names": ("PINK 3 VESTI", "VESTI"),
    },
    "narodnatv.rs": {
        "code": "Narodna_TV",
        "display_names": ("NARODNA TV", "Narodna TV"),
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
    return products


def local_time(value: str) -> datetime:
    # MTS v2 currently labels timestamps +0000, while the website displays the
    # clock portion as Serbian local wall time. Keep the same behaviour used by
    # the rest of this repo's tested MTS v2 importers.
    return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=TZ)


def primary_logo(product: dict) -> str:
    images = product.get("images") or product.get("picture") or product.get("logo") or []
    if isinstance(images, str):
        return images
    if isinstance(images, dict):
        images = [images]
    if not isinstance(images, list):
        return ""
    for image in images:
        if isinstance(image, dict) and image.get("imageType") == "PRIMARY" and image.get("url"):
            return str(image["url"])
    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return str(image["url"])
    return ""


def ensure_channel(root: ET.Element, channel_id: str, names: tuple[str, ...]) -> ET.Element:
    channel = next((node for node in root.findall("channel") if node.get("id") == channel_id), None)
    if channel is None:
        channel = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), channel)
    existing = {(node.text or "").strip() for node in channel.findall("display-name")}
    for name in names:
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = name
    return channel


def replace_schedule(root: ET.Element, channel_id: str, product_rows: list[dict]) -> int:
    for node in list(root.findall("programme")):
        if node.get("channel") == channel_id:
            root.remove(node)

    rows: dict[tuple[datetime, datetime, str], tuple[str, str]] = {}
    for item in product_rows:
        try:
            start = local_time(item["start"])
            stop = local_time(item["end"])
        except Exception:
            continue
        title = str(item.get("title") or "").strip()
        if not title or stop <= start:
            continue
        rows[(start, stop, title)] = (
            str(item.get("description") or "").strip(),
            str(item.get("category") or "").strip(),
        )

    written = 0
    for (start, stop, title), (description, category) in sorted(rows.items(), key=lambda row: row[0][0]):
        programme = ET.SubElement(
            root,
            "programme",
            {
                "channel": channel_id,
                "start": start.strftime("%Y%m%d%H%M%S %z"),
                "stop": stop.strftime("%Y%m%d%H%M%S %z"),
            },
        )
        ET.SubElement(programme, "title", {"lang": "sr"}).text = title
        if description:
            ET.SubElement(programme, "desc", {"lang": "sr"}).text = description
        if category:
            ET.SubElement(programme, "category", {"lang": "sr"}).text = category
        written += 1
    return written


def main(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()

    today = datetime.now(TZ).date()
    products_by_day = {
        day: fetch_products(day.isoformat())
        for day in (today, today + timedelta(days=1))
    }

    for channel_id, spec in TARGETS.items():
        matches = []
        logo = ""
        source_name = ""
        for day, products in products_by_day.items():
            product = next((item for item in products if str(item.get("code") or "") == spec["code"]), None)
            if product is None:
                print(f"WARNING: MTS {spec['code']} missing for {day}")
                continue
            source_name = source_name or str(product.get("name") or "")
            logo = logo or primary_logo(product)
            matches.extend(product.get("programs") or [])

        if not matches:
            raise SystemExit(f"MTS returned no programme data for {channel_id} ({spec['code']})")
        if not logo:
            raise SystemExit(f"MTS returned no logo for {channel_id} ({spec['code']})")

        channel = ensure_channel(root, channel_id, spec["display_names"])
        for icon in list(channel.findall("icon")):
            channel.remove(icon)
        ET.SubElement(channel, "icon", {"src": logo})

        written = replace_schedule(root, channel_id, matches)
        if written < 3:
            raise SystemExit(f"Only {written} programmes written for {channel_id}")
        print(
            f"MTS {channel_id}: code={spec['code']!r}, name={source_name!r}, "
            f"programmes={written}, logo={logo}"
        )

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_pink3_narodna.py guide.xml")
    main(Path(sys.argv[1]))
