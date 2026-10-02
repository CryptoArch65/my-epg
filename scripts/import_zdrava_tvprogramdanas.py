#!/usr/bin/env python3
"""Import Zdrava TV EPG and logo from tvprogramdanas.net."""

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

URL = "https://www.tvprogramdanas.net/zdrava-tv-7"
TZ = ZoneInfo("Europe/Zagreb")
TARGET_IDS = ("343758888241", "zdravatv.hr")


def get(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)", "Accept-Language": "hr-HR,hr;q=0.9"})
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
        if "zdrava" in haystack:
            return urljoin(URL, src)
    for meta in doc.xpath('//meta[@property="og:image"][@content]'):
        src = str(meta.get("content") or "").strip()
        if src and "zdrava" in src.casefold():
            return urljoin(URL, src)
    raise ValueError("Could not identify Zdrava TV logo on TVProgramDanas page")


def ensure_channel(root: ET.Element, channel_id: str, names: tuple[str, ...]) -> ET.Element:
    channel = next((c for c in root.findall("channel") if c.get("id") == channel_id), None)
    if channel is None:
        channel = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), channel)
    existing = {(n.text or "").strip() for n in channel.findall("display-name")}
    for name in names:
        if name not in existing:
            ET.SubElement(channel, "display-name", {"lang": "hr"}).text = name
    return channel


def set_icon(channel: ET.Element, logo: str) -> None:
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": logo})


def add_programme(root: ET.Element, cid: str, start: datetime, stop: datetime, title: str, desc: str, category: str) -> None:
    programme = ET.SubElement(root, "programme", {
        "channel": cid,
        "start": start.strftime("%Y%m%d%H%M%S %z"),
        "stop": stop.strftime("%Y%m%d%H%M%S %z"),
    })
    ET.SubElement(programme, "title", {"lang": "hr"}).text = title
    if desc:
        ET.SubElement(programme, "desc", {"lang": "hr"}).text = desc
    if category:
        ET.SubElement(programme, "category", {"lang": "hr"}).text = category


def main(path: Path) -> None:
    doc = html.fromstring(get(URL))
    canonical = doc.xpath('//link[@rel="canonical"]/@href')
    if canonical and urlparse(canonical[0]).path.rstrip("/") != "/zdrava-tv-7":
        raise ValueError(f"Unexpected Zdrava canonical URL: {canonical[0]!r}")
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
        raise SystemExit(f"TVProgramDanas Zdrava TV only has {len(starts)} programmes")

    tree = ET.parse(path)
    root = tree.getroot()
    source = ensure_channel(root, TARGET_IDS[0], ("Zdrava TV", "ZDRAVA TV"))
    alias = ensure_channel(root, TARGET_IDS[1], ("SR: ZDRAVA TV", "Zdrava TV"))
    set_icon(source, logo)
    set_icon(alias, logo)

    for node in list(root.findall("programme")):
        if node.get("channel") in TARGET_IDS:
            root.remove(node)

    for i, start in enumerate(starts):
        minutes, title, desc, category = events[start]
        stop = start + timedelta(minutes=minutes)
        if i + 1 < len(starts):
            stop = min(stop, starts[i + 1])
        add_programme(root, TARGET_IDS[0], start, stop, title, desc, category)
        add_programme(root, TARGET_IDS[1], start, stop, title, desc, category)

    print(f"Zdrava TV from TVProgramDanas: programmes={len(starts)}, logo={logo}, ids={TARGET_IDS}")
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_zdrava_tvprogramdanas.py guide.xml")
    main(Path(sys.argv[1]))
