#!/usr/bin/env python3
"""Import TV Duga Plus from its official weekly programme schedule.

The broadcaster publishes a repeating Monday-Sunday grid rather than dated
entries. This converts that grid into dated XMLTV programmes around today.
"""

from __future__ import annotations

import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

URL = "https://www.tvdugaplus.com/o-nama/programska-sema/"
TZ = ZoneInfo("Europe/Belgrade")
CHANNEL_ID = "DugaTV.rs"
FALLBACK_LOGO = "https://logos.siptvs.com/EXYU/Fullfull/dugatv.png"
DAYS = {
    "ponedeljak": 0,
    "utorak": 1,
    "sreda": 2,
    "četvrtak": 3,
    "cetvrtak": 3,
    "petak": 4,
    "subota": 5,
    "nedelja": 6,
}


def get(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (EPG guide)",
                "Accept-Language": "sr-RS,sr;q=0.9,en;q=0.5",
            })
            with urlopen(req, timeout=40) as response:
                return response.read(4_000_000)
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise last


def page_logo(doc) -> str:
    candidates = []
    for img in doc.xpath('//img[@src]'):
        src = str(img.get("src") or "").strip()
        haystack = " ".join((src, str(img.get("alt") or ""), str(img.get("title") or ""))).casefold()
        if src and ("duga" in haystack or "logo" in haystack):
            candidates.append(src)
    for src in candidates:
        if src.startswith("https://"):
            return src
        if src.startswith("//"):
            return "https:" + src
        if src.startswith("/"):
            return "https://www.tvdugaplus.com" + src
    return FALLBACK_LOGO


def parse_week(doc):
    lines = [" ".join(line.split()) for line in doc.text_content().splitlines()]
    lines = [line for line in lines if line]
    schedule = {i: [] for i in range(7)}
    current = None
    for line in lines:
        key = line.casefold().strip(":")
        if key in DAYS:
            current = DAYS[key]
            continue
        if current is None:
            continue
        match = re.match(r"^(\d{2}:\d{2})\s+(.+)$", line)
        if not match:
            continue
        clock, title = match.groups()
        hour, minute = map(int, clock.split(":"))
        if hour > 23 or minute > 59:
            continue
        # Avoid duplicated navigation/sidebar text if the page repeats content.
        item = (hour, minute, title.strip())
        if item not in schedule[current]:
            schedule[current].append(item)
    for day, entries in schedule.items():
        entries.sort(key=lambda row: (row[0], row[1]))
        if len(entries) < 2:
            raise ValueError(f"Official Duga schedule has too few entries for weekday {day}: {entries!r}")
    return schedule


def ensure_channel(root: ET.Element, logo: str) -> ET.Element:
    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element("channel", {"id": CHANNEL_ID})
        root.insert(len(root.findall("channel")), channel)
    existing = {(n.text or "").strip() for n in channel.findall("display-name")}
    for name in ("TV Duga plus", "DUGA TV"):
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = name
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": logo})
    return channel


def main(path: Path) -> None:
    try:
        doc = html.fromstring(get(URL))
        weekly = parse_week(doc)
        logo = page_logo(doc)
    except Exception as exc:
        print(f"WARNING official Duga schedule unavailable; keeping existing Duga EPG: {exc!r}")
        return

    today = datetime.now(TZ).date()
    starts = []
    for offset in range(-1, 8):
        day = today + timedelta(days=offset)
        for hour, minute, title in weekly[day.weekday()]:
            starts.append((datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ), title))
    starts.sort(key=lambda row: row[0])

    tree = ET.parse(path)
    root = tree.getroot()
    ensure_channel(root, logo)
    for node in list(root.findall("programme")):
        if node.get("channel") == CHANNEL_ID:
            root.remove(node)

    written = 0
    for index, (start, title) in enumerate(starts):
        if not (today - timedelta(days=1) <= start.date() <= today + timedelta(days=7)):
            continue
        stop = starts[index + 1][0] if index + 1 < len(starts) else start + timedelta(hours=2)
        if stop <= start or stop - start > timedelta(hours=8):
            stop = start + timedelta(hours=1)
        p = ET.SubElement(root, "programme", {
            "channel": CHANNEL_ID,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(p, "title", {"lang": "sr"}).text = title
        written += 1

    if written < 20:
        raise ValueError(f"Official Duga import produced only {written} programmes")

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Duga TV official weekly schedule: programmes={written}, logo={logo}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_duga_official.py guide.xml")
    main(Path(sys.argv[1]))
