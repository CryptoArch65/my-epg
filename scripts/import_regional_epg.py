#!/usr/bin/env python3
"""Import regional TV schedules and host channel logos for the XMLTV guide."""

import csv
import io
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
from PIL import Image


ZONE = ZoneInfo("Europe/Zagreb")
REGIONAL = {
    "RTVBanovina.ba": "rtv-banovina",
    "AuroraTV.hr": "aurora-tv",
    "Z1.hr": "z1",  # MojTV returns HTTP 403 to the scheduled grabber.
    "DiadoraTV.hr": "diadora-tv",
    "LibertasTV.hr": "libertas-tv",
}
LOGOS = {**REGIONAL, "HercegTV.ba": "herceg-tv"}
RTVHB_DAYS = {
    0: "/tv-program/ponedjeljak",
    1: "/tv-program/utorak",
    2: "/tv-program/srijeda",
    3: "/node/714",  # The broadcaster links Thursday to this page.
    4: "/tv-program/petak",
    5: "/tv-program/subota",
    6: "/tv-program/nedjelja",
}
REPO_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"


def download(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)"}), timeout=35) as response:
                return response.read(3_000_000)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def text(node, xpath):
    found = node.xpath(xpath)
    return " ".join(found[0].text_content().split()) if found else ""


def parse_tvprogram(page, channel_id):
    tree = html.fromstring(page)
    expected_slug = REGIONAL[channel_id]
    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    if not canonical or urlparse(canonical[0]).path != "/" + expected_slug:
        raise ValueError(f"Unexpected schedule page for {channel_id}")
    events = []
    today = datetime.now(ZONE).date()
    for tab in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " schedule-tab ")]'):
        match = re.fullmatch(r"schedule-(\d{4}-\d\d-\d\d)", tab.get("id", ""))
        if not match:
            raise ValueError(f"Missing date on {channel_id} schedule")
        date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if not today - timedelta(days=1) <= date <= today + timedelta(days=5):
            continue
        for row in tab.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " timeline-item ")]'):
            clock = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            duration = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " duration ")]')
            title = text(row, './/h3[contains(concat(" ", normalize-space(@class), " "), " program-name ")]')
            minutes = re.fullmatch(r"(\d+)\s*min", duration)
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title or not minutes:
                raise ValueError(f"Incomplete {channel_id} schedule row on {date}")
            start = datetime.strptime(f"{date} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            description = text(row, './/p[contains(concat(" ", normalize-space(@class), " "), " program-desc ")]')
            events.append((start, min(int(minutes.group(1)), 360), title, description))
    if not events:
        print(f"Warning: no current dated programmes for {channel_id}; leaving its schedule empty")
    return events


def parse_rtvhb():
    today = datetime.now(ZONE).date()
    events = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        page = download("https://rtv-hb.com" + RTVHB_DAYS[day.weekday()])
        tree = html.fromstring(page)
        items = tree.xpath('//li[contains(@class,"list-group-item")][.//div[contains(@class,"paragraph--type--emmision-tv")]]')
        if not items:
            raise ValueError(f"RTV HB weekly schedule missing for {day}")
        for item in items:
            period = text(item, './/*[contains(@class,"field--name-field-time-schedule-tv")]')
            title = text(item, './/*[contains(@class,"field--name-field-title-schedule-tv")]')
            times = re.findall(r"\b([012]?\d:[0-5]\d)\b", period)
            if not times or not title:
                raise ValueError(f"Incomplete RTV HB entry for {day}: {period!r}")
            start = datetime.strptime(f"{day} {times[0]}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            stop = datetime.strptime(f"{day} {times[1]}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE) if len(times) > 1 else start + timedelta(hours=1)
            if stop <= start:
                stop += timedelta(days=1)
            description = text(item, './/*[contains(@class,"field--name-field-description")]')
            events.append((start, min(int((stop - start).total_seconds() / 60), 480), title, description))
    return events


def append_programmes(root, channel_id, events):
    # A few source rows overlap; the next broadcast start takes precedence.
    unique = {}
    for start, minutes, title, description in events:
        unique.setdefault(start, (minutes, title, description))
    starts = sorted(unique)
    written = 0
    for index, start in enumerate(starts):
        minutes, title, description = unique[start]
        stop = start + timedelta(minutes=minutes)
        if index + 1 < len(starts):
            stop = min(stop, starts[index + 1])
        if stop <= start:
            continue
        node = ET.SubElement(root, "programme", {
            "channel": channel_id,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(node, "title", lang="hr").text = title
        if description:
            ET.SubElement(node, "desc", lang="hr").text = description
        written += 1
    print(f"Imported {written} programmes for {channel_id}")


def host_logos(pages, csv_path, logo_dir):
    with csv_path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["guide_id", "logo_url"]:
            raise ValueError("Unexpected channel logo CSV header")
        rows = list(reader)
    by_id = {row["guide_id"]: row for row in rows}
    logo_dir.mkdir(parents=True, exist_ok=True)
    for channel_id, slug in LOGOS.items():
        filename = "regional-" + slug + ".png"
        path = logo_dir / filename
        if not path.is_file():
            tree = html.fromstring(pages[slug])
            sources = tree.xpath('//img[contains(@src,"/uploads/logos/")]/@src')
            if len(sources) != 1 or urlparse(sources[0]).path != "/uploads/logos/" + slug + ".webp":
                raise ValueError(f"Unexpected {channel_id} logo source")
            with Image.open(io.BytesIO(download(sources[0]))) as image:
                buffer = io.BytesIO()
                image.convert("RGBA").save(buffer, format="PNG")
                path.write_bytes(buffer.getvalue())
        url = REPO_LOGO + filename
        if channel_id in by_id:
            by_id[channel_id]["logo_url"] = url
        else:
            row = {"guide_id": channel_id, "logo_url": url}
            rows.append(row)
            by_id[channel_id] = row
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(guide_path, config_path, logos_csv, logos_dir):
    configured = ET.parse(config_path).getroot()
    if configured.tag != "channels" or {c.get("xmltv_id") for c in configured} != set(REGIONAL) | {"RTVHB.ba"}:
        raise ValueError("Regional channel configuration differs from importer")
    pages = {slug: download("https://www.tvprogramdanas.net/" + slug) for slug in set(LOGOS.values())}
    schedules = {id: parse_tvprogram(pages[slug], id) for id, slug in REGIONAL.items()}
    schedules["RTVHB.ba"] = parse_rtvhb()
    host_logos(pages, logos_csv, logos_dir)

    tree = ET.parse(guide_path)
    root = tree.getroot()
    channels = root.findall("channel")
    existing = {c.get("id") for c in channels}
    for index, configured_channel in enumerate(configured):
        channel_id = configured_channel.get("xmltv_id")
        if channel_id in existing:
            raise ValueError(f"Duplicate channel in generated guide: {channel_id}")
        node = ET.Element("channel", id=channel_id)
        ET.SubElement(node, "display-name", lang="hr").text = configured_channel.text
        root.insert(len(channels) + index, node)
    for channel_id, events in schedules.items():
        append_programmes(root, channel_id, events)
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Usage: import_regional_epg.py guide.xml regional-channels.xml logos.csv logos-dir")
    main(*(Path(arg) for arg in sys.argv[1:]))
