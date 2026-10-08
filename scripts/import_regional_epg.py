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


def parse_slon(page):
    tree = html.fromstring(page)
    today = datetime.now(ZONE).date()
    events = []
    seen_days = set()
    for heading in tree.xpath('//h2[contains(., "TV program za")]'):
        match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", heading.text_content())
        if not match:
            continue
        day = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
        if day in seen_days:
            continue
        if day < today - timedelta(days=1) or day > today + timedelta(days=7):
            continue
        seen_days.add(day)
        listing = heading.getnext()
        if listing is None or listing.tag != "p":
            raise ValueError(f"RTV Slon schedule layout changed for {day}")
        for raw in listing.xpath("./text()"):
            entry = " ".join(raw.split())
            programme = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)\s+(.+)", entry)
            if not programme:
                if entry:
                    raise ValueError(f"Unexpected RTV Slon programme: {entry!r}")
                continue
            start = datetime.strptime(f"{day} {programme.group(1)}:{programme.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            events.append((start, 180, programme.group(3), ""))
    if today not in seen_days or not events:
        raise ValueError("RTV Slon current dated schedule missing")
    return events


def parse_mytv(page, day):
    tree = html.fromstring(page)
    active = tree.xpath('//a[contains(concat(" ", normalize-space(@class), " "), " is-active ") and contains(@class,"tvschedule-epg__cp-weekday")]/@href')
    if len(active) != 1 or "epg_day=" + day.isoformat() not in active[0]:
        raise ValueError(f"MY TV page did not select {day}")
    rows = tree.xpath('//button[contains(concat(" ", normalize-space(@class), " "), " tvschedule-epg__cp-row ")]')
    if not rows:
        if day > datetime.now(ZONE).date():
            return []  # The date is selectable before its schedule is published.
        raise ValueError(f"MY TV has no programme rows for {day}")
    events = []
    for index, row in enumerate(rows):
        period = row.get("data-program-time", "")
        match = re.fullmatch(r"(\d\d:\d\d)\s*[–-]\s*(\d\d:\d\d)", period)
        title = row.get("data-program-title", "").strip()
        if not match or not title:
            raise ValueError(f"Incomplete MY TV programme on {day}: {period!r}")
        if index == 0 and len(rows) > 1:
            following = re.match(r"\d\d:\d\d", rows[1].get("data-program-time", ""))
            if following and match.group(1) > following.group() and int(match.group(1)[:2]) >= 20:
                continue  # The first overnight row belongs to yesterday.
        start = datetime.strptime(f"{day} {match.group(1)}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
        stop = datetime.strptime(f"{day} {match.group(2)}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
        if stop <= start:
            stop += timedelta(days=1)
        duration = int((stop - start).total_seconds() // 60)
        if not 0 < duration <= 720:
            raise ValueError(f"Unexpected MY TV duration on {day}: {period!r}")
        events.append((start, duration, title, row.get("data-program-description", "").strip()))
    return events


def fetch_mytv():
    today = datetime.now(ZONE).date()
    first = download("https://mymedia.ba/tv-program/")
    tree = html.fromstring(first)
    available = {datetime.strptime(value, "%Y-%m-%d").date() for value in
                 re.findall(r"epg_day=(\d{4}-\d\d-\d\d)", " ".join(tree.xpath('//a[contains(@class,"tvschedule-epg__cp-weekday")]/@href')))}
    if today not in available:
        raise ValueError("MY TV has no schedule for today")
    events = parse_mytv(first, today)
    for day in sorted(d for d in available if today < d <= today + timedelta(days=3)):
        events.extend(parse_mytv(download("https://mymedia.ba/tv-program/?epg_day=" + day.isoformat()), day))
    return events


def parse_rtl_world(page, day):
    tree = html.fromstring(page)
    heading = " ".join(tree.xpath('//text()'))
    if not re.search(r"Tv program\s+\w+,\s*" + day.strftime("%d.%m.%Y") + r"\.", heading):
        raise ValueError(f"RTL Croatia World page date changed for {day}")
    rows = tree.xpath('//ul[contains(concat(" ", normalize-space(@class), " "), " channel-items ")]/li')
    if not rows:
        raise ValueError(f"RTL Croatia World programme rows missing for {day}")
    events = []
    for row in rows:
        clock = text(row, './span[contains(@class,"channel-item-time")]')
        title = text(row, './span[contains(@class,"channel-item-title")]')
        if not re.fullmatch(r"\d\d:\d\d", clock) or not title:
            raise ValueError(f"Incomplete RTL Croatia World programme for {day}")
        start = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
        events.append((start, 180, title, ""))
    return events


def fetch_rtl_world():
    today = datetime.now(ZONE).date()
    events = []
    for offset in range(3):
        day = today + timedelta(days=offset)
        url = "https://www.tvprogram24.rs/rtl-croatia-world?datum=" + day.isoformat()
        events.extend(parse_rtl_world(download(url), day))
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
    if configured.tag != "channels" or {c.get("xmltv_id") for c in configured} != set(REGIONAL) | {"RTVHB.ba", "TVSlonExtra.ba", "MYTV.ba", "RTLCroatiaWorld.hr"}:
        raise ValueError("Regional channel configuration differs from importer")
    pages = {slug: download("https://www.tvprogramdanas.net/" + slug) for slug in set(LOGOS.values())}
    schedules = {id: parse_tvprogram(pages[slug], id) for id, slug in REGIONAL.items()}
    schedules["RTVHB.ba"] = parse_rtvhb()
    schedules["TVSlonExtra.ba"] = parse_slon(download("https://www.rtvslon.ba/tv-program/"))
    try:
        schedules["MYTV.ba"] = fetch_mytv()
    except (OSError, ValueError) as exc:
        print(f"Warning: MY TV source unavailable: {exc}")
        schedules["MYTV.ba"] = []
    try:
        schedules["RTLCroatiaWorld.hr"] = fetch_rtl_world()
    except (OSError, ValueError) as exc:
        print(f"Warning: RTL Croatia World source unavailable: {exc}")
        schedules["RTLCroatiaWorld.hr"] = []
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
        if channel_id == "RTLCroatiaWorld.hr":
            # Match the names used for SD and HD variants in the provider playlist.
            for name in ("|HR| RTL CROATIA WORLD", "|HR| RTL CROATIA WORLD HD"):
                ET.SubElement(node, "display-name", lang="hr").text = name
        root.insert(len(channels) + index, node)
    for channel_id, events in schedules.items():
        append_programmes(root, channel_id, events)
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Usage: import_regional_epg.py guide.xml regional-channels.xml logos.csv logos-dir")
    main(*(Path(arg) for arg in sys.argv[1:]))
