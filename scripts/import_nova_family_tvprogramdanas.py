#!/usr/bin/env python3
"""Import Nova Family schedule from tvprogramdanas.net into an XMLTV guide."""

import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

ZONE = ZoneInfo("Europe/Zagreb")
CHANNEL_ID = "nova-plus-family"
CHANNEL_NAME = "|HR| NOVA FAMILY HD"
URL = "https://www.tvprogramdanas.net/nova-family"


def download(url):
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)"})
            with urlopen(req, timeout=35) as response:
                return response.read(3_000_000)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def text(node, xpath):
    found = node.xpath(xpath)
    return " ".join(found[0].text_content().split()) if found else ""


def parse_schedule(page):
    tree = html.fromstring(page)
    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    if not canonical or urlparse(canonical[0]).path.rstrip("/") != "/nova-family":
        raise ValueError("Unexpected Nova Family schedule page")

    today = datetime.now(ZONE).date()
    events = []
    for tab in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " schedule-tab ")]'):
        match = re.fullmatch(r"schedule-(\d{4}-\d\d-\d\d)", tab.get("id", ""))
        if not match:
            raise ValueError("Nova Family schedule tab missing date")
        day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if not today - timedelta(days=1) <= day <= today + timedelta(days=5):
            continue
        for row in tab.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " timeline-item ")]'):
            clock = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            duration = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " duration ")]')
            title = text(row, './/h3[contains(concat(" ", normalize-space(@class), " "), " program-name ")]')
            minutes = re.fullmatch(r"(\d+)\s*min", duration)
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title or not minutes:
                raise ValueError(f"Incomplete Nova Family schedule row on {day}")
            start = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            desc = text(row, './/p[contains(concat(" ", normalize-space(@class), " "), " program-desc ")]')
            events.append((start, min(int(minutes.group(1)), 360), title, desc))

    if not events:
        raise ValueError("Nova Family returned no current programme data")
    return events


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()

    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element("channel", id=CHANNEL_ID)
        ET.SubElement(channel, "display-name", lang="hr").text = CHANNEL_NAME
        channels = root.findall("channel")
        root.insert(len(channels), channel)
    elif not channel.findall("display-name"):
        ET.SubElement(channel, "display-name", lang="hr").text = CHANNEL_NAME

    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)

    events = parse_schedule(download(URL))
    unique = {}
    for start, minutes, title, desc in events:
        unique.setdefault(start, (minutes, title, desc))
    starts = sorted(unique)

    for index, start in enumerate(starts):
        minutes, title, desc = unique[start]
        stop = start + timedelta(minutes=minutes)
        if index + 1 < len(starts):
            stop = min(stop, starts[index + 1])
        if stop <= start:
            continue
        node = ET.SubElement(root, "programme", {
            "channel": CHANNEL_ID,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(node, "title", lang="hr").text = title
        if desc:
            ET.SubElement(node, "desc", lang="hr").text = desc

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Imported {len(starts)} Nova Family programmes from tvprogramdanas.net")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_nova_family_tvprogramdanas.py guide.xml")
    main(Path(sys.argv[1]))
