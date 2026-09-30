#!/usr/bin/env python3
"""Import Nova World schedule and logo from TVEpg.eu into the Croatia guide."""

import io
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html
from PIL import Image

CHANNEL_ID = "prvaworld.rs"
DISPLAY_NAME = "Nova World"
PAGE_URL = "https://tvepg.eu/hr/croatia/channel/nova_world"
LOGO_URL = "https://tvepg.eu/img/croatia/logo/nova-world.webp"
REPO_LOGO_URL = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/tvepg-nova-world.png"
ZONE = ZoneInfo("Europe/Zagreb")


def download(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)"})
    with urlopen(request, timeout=35) as response:
        return response.read(5_000_000)


def parse_schedule(page):
    tree = html.fromstring(page)
    events = []
    current_day = None
    day_events = []

    def flush_day():
        nonlocal day_events
        if not current_day or not day_events:
            day_events = []
            return
        # TVEpg sometimes shows the final programme from the previous evening
        # before the midnight entries for the selected date. Skip that carry-over.
        if len(day_events) > 1 and day_events[0][0].hour >= 20 and day_events[1][0].hour < 6:
            day_events = day_events[1:]
        events.extend(day_events)
        day_events = []

    for node in tree.iter():
        if node.tag in {"h4", "h5", "h6"}:
            heading = " ".join(node.text_content().split())
            match = re.search(r"(\d{2})\.\s*(\d{2})\.\s*(\d{4})", heading)
            if match:
                flush_day()
                current_day = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1))).date()
                continue
        if current_day is None or node.tag != "a":
            continue
        label = " ".join(node.text_content().split())
        match = re.match(r"^(\d{1,2}):(\d{2})\s+(.+)$", label)
        if not match:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        title = match.group(3).strip()
        if not (0 <= hour <= 23 and 0 <= minute <= 59) or not title:
            continue
        start = datetime.combine(current_day, datetime.min.time(), tzinfo=ZONE).replace(hour=hour, minute=minute)
        day_events.append((start, title))
    flush_day()

    unique = {}
    for start, title in events:
        unique.setdefault(start, title)
    starts = sorted(unique)
    if not starts:
        raise ValueError("TVEpg Nova World page returned no programme rows")

    today = datetime.now(ZONE).date()
    starts = [s for s in starts if today - timedelta(days=1) <= s.date() <= today + timedelta(days=7)]
    if not starts:
        raise ValueError("TVEpg Nova World page has no current dated programmes")
    return [(start, unique[start]) for start in starts]


def write_logo(logo_dir):
    logo_dir.mkdir(parents=True, exist_ok=True)
    path = logo_dir / "tvepg-nova-world.png"
    raw = download(LOGO_URL)
    with Image.open(io.BytesIO(raw)) as image:
        image.convert("RGBA").save(path, format="PNG")
    return path


def main(guide_path, logo_dir):
    events = parse_schedule(download(PAGE_URL))
    write_logo(logo_dir)

    tree = ET.parse(guide_path)
    root = tree.getroot()

    # Replace any previous Nova World schedule for this playlist ID.
    for programme in list(root.findall("programme")):
        if programme.get("channel") == CHANNEL_ID:
            root.remove(programme)

    channel = next((c for c in root.findall("channel") if c.get("id") == CHANNEL_ID), None)
    if channel is None:
        channel = ET.Element("channel", id=CHANNEL_ID)
        ET.SubElement(channel, "display-name", lang="hr").text = DISPLAY_NAME
        channels = root.findall("channel")
        root.insert(len(channels), channel)
    elif not channel.findall("display-name"):
        ET.SubElement(channel, "display-name", lang="hr").text = DISPLAY_NAME

    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", src=REPO_LOGO_URL)

    written = 0
    for index, (start, title) in enumerate(events):
        if index + 1 < len(events):
            stop = events[index + 1][0]
            if stop <= start or stop - start > timedelta(hours=12):
                stop = start + timedelta(hours=1)
        else:
            stop = start + timedelta(hours=1)
        programme = ET.SubElement(root, "programme", {
            "channel": CHANNEL_ID,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(programme, "title", lang="hr").text = title
        written += 1

    if written == 0:
        raise ValueError("No Nova World programmes written")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"Imported {written} programmes for {CHANNEL_ID} from TVEpg.eu")
    print(f"Hosted Nova World logo at {REPO_LOGO_URL}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_nova_world_tvepg.py guide.xml logos-dir")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
