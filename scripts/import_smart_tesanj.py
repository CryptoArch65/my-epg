#!/usr/bin/env python3
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html
from PIL import Image

ZONE = ZoneInfo("Europe/Sarajevo")
SMART_URL = "https://tvsmart.ba/tv-program/"
SMART_LOGO = "https://tvsmart.ba/wp-content/uploads/2021/02/LOGO-SMART-e1614116345380.png"
CHANNEL_ID = "SmartTVTesanj.ba"
DISPLAY_NAME = "|BIH| SMART TV Tesanj"
LOGO_FILENAME = "smart-tv-tesanj.png"
REPO_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/" + LOGO_FILENAME

WEEKDAYS = {
    "ponedjeljak", "utorak", "srijeda", "četvrtak", "cetvrtak",
    "petak", "subota", "nedjelja"
}


def download(url):
    for attempt in range(3):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)"})
            with urlopen(req, timeout=35) as response:
                return response.read(5_000_000)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def host_logo(logos_dir):
    raw = download(SMART_LOGO)
    path = logos_dir / LOGO_FILENAME
    with Image.open(io.BytesIO(raw)) as image:
        image.convert("RGBA").save(path, format="PNG")
    return REPO_LOGO


def clean_text(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n-–—")


def parse_page(page):
    tree = html.fromstring(page)
    text = " ".join(t.strip() for t in tree.xpath("//body//text()") if t.strip())
    text = clean_text(text)

    heading = re.search(r"Smart\s*TV\s*[–—-]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})", text, re.I)
    if not heading:
        raise ValueError("Smart TV page date heading not found")
    day = datetime(
        int(heading.group(3)),
        int(heading.group(2)),
        int(heading.group(1)),
        tzinfo=ZONE,
    ).date()

    section = text[heading.end():]
    end_candidates = [
        pos for marker in (" TV PROGRAM ", " Arhiva ", " Kategorije ")
        if (pos := section.find(marker)) >= 0
    ]
    if end_candidates:
        section = section[:min(end_candidates)]

    first_time = re.search(r"(?<!\d)([0-2]?\d:[0-5]\d)\s+", section)
    if not first_time:
        raise ValueError(f"No Smart TV schedule entries found for {day}")
    section = section[first_time.start():]

    pattern = re.compile(
        r"(?<!\d)([0-2]?\d:[0-5]\d)\s+(.+?)"
        r"(?=(?:\s+[0-2]?\d:[0-5]\d\s+)|$)"
    )
    rows = []
    for match in pattern.finditer(section):
        clock = match.group(1)
        title = clean_text(match.group(2))
        title = re.sub(
            r"^(?:Ponedjeljak|Utorak|Srijeda|Četvrtak|Cetvrtak|Petak|Subota|Nedjelja)\s+",
            "",
            title,
            flags=re.I,
        )
        if title:
            rows.append((clock, title))

    deduped = []
    seen = set()
    for row in rows:
        if row in seen:
            continue
        seen.add(row)
        deduped.append(row)

    if len(deduped) < 6:
        raise ValueError(f"Smart TV schedule too short for {day}: {len(deduped)} rows")
    return day, deduped, tree


def nav_urls(tree):
    urls = {SMART_URL}
    for node in tree.xpath("//a[@href]"):
        label = clean_text(" ".join(node.itertext())).lower()
        href = node.get("href", "")
        if label in WEEKDAYS and "tv-program" in href:
            urls.add(urljoin(SMART_URL, href))
    return urls


def collect_schedules():
    base = download(SMART_URL)
    base_day, base_rows, tree = parse_page(base)
    schedules = {base_day: base_rows}
    urls = nav_urls(tree)

    for url in sorted(urls):
        if url == SMART_URL:
            continue
        try:
            day, rows, _ = parse_page(download(url))
        except Exception as exc:
            print(f"WARNING: Smart TV page skipped {url}: {exc}")
            continue
        schedules[day] = rows

    return schedules


def build_events(schedules):
    events = []
    for day in sorted(schedules):
        rows = schedules[day]
        starts = []
        for clock, title in rows:
            start = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            starts.append((start, title))
        starts.sort(key=lambda row: row[0])

        for index, (start, title) in enumerate(starts):
            if index + 1 < len(starts):
                stop = starts[index + 1][0]
            else:
                stop = start + timedelta(hours=1)
            if stop <= start:
                continue
            events.append((start, stop, title))
    return events


def upsert_channel(root, logo_url):
    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element("channel", {"id": CHANNEL_ID})
        root.insert(len(root.findall("channel")), channel)
    for child in list(channel):
        if child.tag in {"display-name", "icon"}:
            channel.remove(child)
    ET.SubElement(channel, "display-name", {"lang": "bs"}).text = DISPLAY_NAME
    ET.SubElement(channel, "icon", {"src": logo_url})
    return channel


def replace_programmes(root, events):
    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)
    for start, stop, title in events:
        node = ET.SubElement(root, "programme", {
            "channel": CHANNEL_ID,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(node, "title", {"lang": "bs"}).text = title


def main(guide_path, logos_dir):
    logos_dir.mkdir(parents=True, exist_ok=True)
    try:
        hosted_logo = host_logo(logos_dir)
    except Exception as exc:
        hosted_logo = SMART_LOGO
        print(f"WARNING: Smart TV Tešanj logo could not be hosted; using official URL directly: {exc}")

    tree = ET.parse(guide_path)
    root = tree.getroot()
    upsert_channel(root, hosted_logo)

    try:
        schedules = collect_schedules()
    except Exception as exc:
        print(f"WARNING: Smart TV Tešanj EPG fetch failed; logo/channel kept: {exc}")
        tree.write(guide_path, encoding="utf-8", xml_declaration=True)
        return

    today = datetime.now(ZONE).date()
    dates = sorted(schedules)
    fresh_dates = [day for day in dates if today - timedelta(days=2) <= day <= today + timedelta(days=8)]

    if not fresh_dates:
        newest = dates[-1] if dates else None
        print(
            "WARNING: Smart TV Tešanj page is stale; "
            f"page dates={dates[0] if dates else None}..{newest}, today={today}. "
            "Keeping official logo/channel but not publishing old EPG as current."
        )
        tree.write(guide_path, encoding="utf-8", xml_declaration=True)
        return

    fresh = {day: schedules[day] for day in fresh_dates}
    events = build_events(fresh)
    if len(events) < 10:
        print(
            f"WARNING: Smart TV Tešanj current schedule too short ({len(events)} programmes); "
            "keeping logo/channel without replacing EPG."
        )
        tree.write(guide_path, encoding="utf-8", xml_declaration=True)
        return

    replace_programmes(root, events)
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(
        f"Smart TV Tešanj: imported {len(events)} programmes "
        f"for {fresh_dates[0]}..{fresh_dates[-1]}; logo={hosted_logo}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_smart_tesanj.py guide.xml logos-dir")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
