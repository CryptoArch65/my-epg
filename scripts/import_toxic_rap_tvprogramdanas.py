#!/usr/bin/env python3
"""Import Toxic Rap EPG and logo from TVProgramDanas when provider feeds are empty."""

from __future__ import annotations

import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html

URL = "https://www.tvprogramdanas.net/toxic-rap"
TZ = ZoneInfo("Europe/Belgrade")
CHANNEL_ID = "ToxicRap.ba"


def get(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (EPG guide)",
                "Accept-Language": "sr-RS,sr;q=0.9,hr;q=0.8,en;q=0.6",
            })
            with urlopen(req, timeout=40) as response:
                return response.read(4_000_000)
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise last


def text(node, xpath: str) -> str:
    found = node.xpath(xpath)
    return " ".join(found[0].text_content().split()) if found else ""


def find_logo(doc) -> str:
    for img in doc.xpath('//img[@src]'):
        src = str(img.get("src") or "").strip()
        haystack = " ".join((src, str(img.get("alt") or ""), str(img.get("title") or ""))).casefold()
        if "toxic" in haystack and "rap" in haystack:
            return urljoin(URL, src)
    for meta in doc.xpath('//meta[@property="og:image"][@content] | //meta[@name="twitter:image"][@content]'):
        src = str(meta.get("content") or "").strip()
        if src:
            return urljoin(URL, src)
    # TVProgramDanas uses this stable naming convention for channel logos.
    return "https://www.tvprogramdanas.net/uploads/logos/toxic-rap.webp"


def ensure_channel(root: ET.Element) -> ET.Element:
    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element("channel", {"id": CHANNEL_ID})
        root.insert(len(root.findall("channel")), channel)
    existing = {(n.text or "").strip() for n in channel.findall("display-name")}
    for name in ("Toxic Rap", "TOXIC RAP"):
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = name
    return channel


def main(path: Path) -> None:
    try:
        doc = html.fromstring(get(URL))
    except Exception as exc:
        print(f"WARNING Toxic Rap TVProgramDanas unavailable; keeping previous guide data: {exc!r}")
        return

    canonical = doc.xpath('//link[@rel="canonical"]/@href')
    if canonical and urlparse(canonical[0]).path.rstrip("/") != "/toxic-rap":
        print(f"WARNING unexpected Toxic Rap canonical URL {canonical[0]!r}; keeping previous guide data")
        return

    logo = find_logo(doc)
    today = datetime.now(TZ).date()
    events = {}
    for tab in doc.xpath('//div[contains(concat(" ",normalize-space(@class)," ")," schedule-tab ")]'):
        match = re.fullmatch(r"schedule-(\d{4}-\d\d-\d\d)", tab.get("id", ""))
        if not match:
            continue
        day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if not today - timedelta(days=1) <= day <= today + timedelta(days=7):
            continue
        for row in tab.xpath('.//div[contains(concat(" ",normalize-space(@class)," ")," timeline-item ")]'):
            clock = text(row, './/span[contains(concat(" ",normalize-space(@class)," ")," time ")]')
            duration = text(row, './/span[contains(concat(" ",normalize-space(@class)," ")," duration ")]')
            title = text(row, './/h3[contains(concat(" ",normalize-space(@class)," ")," program-name ")]')
            minutes = re.fullmatch(r"(\d+)\s*min", duration)
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title or not minutes:
                continue
            start = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
            desc = text(row, './/p[contains(concat(" ",normalize-space(@class)," ")," program-desc ")]')
            category = text(row, './/*[contains(concat(" ",normalize-space(@class)," ")," category ")]')
            events[start] = (min(int(minutes.group(1)), 720), title, desc, category)

    starts = sorted(events)
    if len(starts) < 3:
        print(f"WARNING Toxic Rap TVProgramDanas only returned {len(starts)} programmes; keeping previous guide data")
        return

    tree = ET.parse(path)
    root = tree.getroot()
    channel = ensure_channel(root)
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": logo})

    for node in list(root.findall("programme")):
        if node.get("channel") == CHANNEL_ID:
            root.remove(node)

    written = 0
    for i, start in enumerate(starts):
        minutes, title, desc, category = events[start]
        stop = start + timedelta(minutes=minutes)
        if i + 1 < len(starts):
            stop = min(stop, starts[i + 1])
        p = ET.SubElement(root, "programme", {
            "channel": CHANNEL_ID,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(p, "title", {"lang": "sr"}).text = title
        if desc:
            ET.SubElement(p, "desc", {"lang": "sr"}).text = desc
        if category:
            ET.SubElement(p, "category", {"lang": "sr"}).text = category
        written += 1

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"Toxic Rap from TVProgramDanas: programmes={written}, logo={logo}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_toxic_rap_tvprogramdanas.py guide.xml")
    main(Path(sys.argv[1]))
