#!/usr/bin/env python3
import io
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
from PIL import Image

ZONE = ZoneInfo("Europe/Sarajevo")
REPO_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"
PODRINJE_URL = "https://podrinjemedia.ba/programska-sema/"

CHANNELS = {
    "TVZivinice.ba": {
        "name": "|BIH| TV ZIVINICE",
        "logo": "https://rtvzivinice.tv/wp-content/uploads/2018/03/LOGO-TVZ-PRIMJER-1.png",
        "filename": "tv-zivinice.png",
    },
    "RTVCazin.ba": {
        "name": "|BIH| RTV CAZIN",
        "logo": "https://crt.ba/wp-content/uploads/2021/11/crtLogo.png",
        "filename": "rtv-cazin.png",
    },
    "TVPodrinje.ba": {
        "name": "|BIH| TV PODRINJE",
        "logo": None,
        "filename": "tv-podrinje.png",
    },
}

DAY_NAMES = {
    "ponedjeljak": 0,
    "utorak": 1,
    "srijeda": 2,
    "četvrtak": 3,
    "cetvrtak": 3,
    "petak": 4,
    "subota": 5,
    "nedjelja": 6,
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


def host_png(url, path):
    raw = download(url)
    with Image.open(io.BytesIO(raw)) as image:
        image.convert("RGBA").save(path, format="PNG")


def discover_podrinje_logo(page):
    tree = html.fromstring(page)
    base = PODRINJE_URL
    candidates = []
    for node in tree.xpath("//img[@src]"):
        src = urljoin(base, node.get("src"))
        marker = " ".join([
            src,
            node.get("alt", ""),
            node.get("class", ""),
            node.get("id", ""),
        ]).lower()
        score = 0
        if "logo" in marker:
            score += 4
        if "podrinje" in marker:
            score += 3
        if "header" in marker or "brand" in marker:
            score += 2
        if urlparse(src).netloc.endswith("podrinjemedia.ba"):
            score += 1
        if score:
            candidates.append((score, src))
    if not candidates:
        raise ValueError("Could not find TV Podrinje logo on broadcaster page")
    candidates.sort(reverse=True)
    print("TV Podrinje logo source:", candidates[0][1])
    return candidates[0][1]


def clean_block(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip(" -–—\t\r\n")
    text = re.sub(r"\s+[–—-]\s+", " / ", text)
    text = re.sub(r"\s*/\s*", " / ", text)
    return text.strip(" /-")


def parse_weekly_schedule(page):
    tree = html.fromstring(page)
    # WordPress currently renders the tabby shortcodes as visible text. Keep the
    # parser tolerant of straight/curly quotes and minor whitespace changes.
    text = " ".join(t.strip() for t in tree.xpath("//body//text()") if t.strip())
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    marker = re.compile(
        r"\[tabby\s+title\s*=\s*[\"”']?"
        r"(Ponedjeljak|Utorak|Srijeda|Četvrtak|Cetvrtak|Petak|Subota|Nedjelja)"
        r"[\"”']?\]",
        re.I,
    )
    matches = list(marker.finditer(text))
    if len(matches) < 7:
        raise ValueError(f"TV Podrinje weekday sections changed: found {len(matches)}")

    weekly = {}
    clock_re = re.compile(r"(?<!\d)([0-2]?\d:[0-5]\d)(?:\s*[–—-]\s*([0-2]?\d:[0-5]\d))?")
    for index, match in enumerate(matches):
        raw_day = match.group(1).lower()
        weekday = DAY_NAMES[raw_day]
        end = matches[index + 1].start() if index + 1 < len(matches) else text.find("[tabbyending]", match.end())
        if end < 0:
            end = len(text)
        section = text[match.end():end]
        times = list(clock_re.finditer(section))
        blocks = []
        for i, tm in enumerate(times):
            start_clock = tm.group(1)
            explicit_stop = tm.group(2)
            chunk_end = times[i + 1].start() if i + 1 < len(times) else len(section)
            title = clean_block(section[tm.end():chunk_end])
            if not title:
                continue
            blocks.append((start_clock, explicit_stop, title))
        if len(blocks) < 5:
            raise ValueError(f"TV Podrinje schedule too short for {raw_day}: {len(blocks)} blocks")
        weekly[weekday] = blocks
    return weekly


def next_date_for_weekday(base, weekday, offset_weeks=0):
    return base + timedelta(days=(weekday - base.weekday()) % 7 + 7 * offset_weeks)


def build_podrinje_events(weekly):
    today = datetime.now(ZONE).date()
    events = []
    # Generate today through the next 7 days from the station's recurring weekly grid.
    for offset in range(8):
        day = today + timedelta(days=offset)
        blocks = weekly[day.weekday()]
        starts = []
        for start_clock, explicit_stop, title in blocks:
            start = datetime.strptime(f"{day} {start_clock}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
            # 00:00 appears after the late-night blocks and means the following midnight.
            if start_clock == "00:00":
                start += timedelta(days=1)
            starts.append((start, explicit_stop, title))
        starts.sort(key=lambda row: row[0])
        for i, (start, explicit_stop, title) in enumerate(starts):
            if explicit_stop:
                stop = datetime.strptime(f"{start.date()} {explicit_stop}", "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
                if stop <= start:
                    stop += timedelta(days=1)
            elif i + 1 < len(starts):
                stop = starts[i + 1][0]
            else:
                stop = start + timedelta(hours=1)
            if stop <= start:
                continue
            events.append((start, stop, title))
    return events


def upsert_channel(root, channel_id, display_name, logo_url):
    existing = next((c for c in root.findall("channel") if c.get("id") == channel_id), None)
    if existing is None:
        existing = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), existing)
    for child in list(existing):
        if child.tag in {"display-name", "icon"}:
            existing.remove(child)
    ET.SubElement(existing, "display-name", {"lang": "bs"}).text = display_name
    ET.SubElement(existing, "icon", {"src": logo_url})


def main(guide_path, logos_dir):
    logos_dir.mkdir(parents=True, exist_ok=True)
    page = download(PODRINJE_URL)
    CHANNELS["TVPodrinje.ba"]["logo"] = discover_podrinje_logo(page)
    weekly = parse_weekly_schedule(page)
    events = build_podrinje_events(weekly)
    if len(events) < 40:
        raise SystemExit(f"TV Podrinje imported too few programmes: {len(events)}")

    hosted = {}
    for channel_id, cfg in CHANNELS.items():
        path = logos_dir / cfg["filename"]
        host_png(cfg["logo"], path)
        hosted[channel_id] = REPO_LOGO + cfg["filename"]

    tree = ET.parse(guide_path)
    root = tree.getroot()
    for channel_id, cfg in CHANNELS.items():
        upsert_channel(root, channel_id, cfg["name"], hosted[channel_id])

    for p in list(root.findall("programme")):
        if p.get("channel") == "TVPodrinje.ba":
            root.remove(p)
    for start, stop, title in events:
        node = ET.SubElement(root, "programme", {
            "channel": "TVPodrinje.ba",
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(node, "title", {"lang": "bs"}).text = title

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)
    print(f"TV Podrinje: imported {len(events)} programme blocks")
    print("Added/updated BIH local logos: TV Zivinice, RTV Cazin, TV Podrinje")

    # Smart TV Tešanj has its own official-site importer. It is intentionally
    # freshness-aware so an archived station page can never be published as current EPG.
    from import_smart_tesanj import main as import_smart_tesanj
    import_smart_tesanj(guide_path, logos_dir)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_bih_local_channels.py guide.xml logos-dir")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
