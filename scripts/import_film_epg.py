#!/usr/bin/env python3
"""Add film channel broadcaster schedules and logos to the XMLTV guide."""

import csv
import io
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import cairosvg
from lxml import html
from PIL import Image


ZONE = ZoneInfo("Europe/Zagreb")
AXN_URL = "https://axn.hr/program-tv/"
M1_URLS = {
    "M1Film.hr": "https://www.m1film.hr/hr/epg/",
    "M1Gold.hr": "https://www.m1film.hr/gold/epg/",
}
SUPERSTAR_URL = "https://superstartv.rs/programske-seme/"
DIZI_URL = "https://www.tvprogramdanas.net/dizi"
SUPERSTAR_TABS = {
    "SuperstarTV1.rs": "elementor-tab-content-1641",
    "SuperstarTV2.rs": "elementor-tab-content-1642",
    "SuperstarTV3.rs": "elementor-tab-content-1643",
}
LOGOS = {
    "AXN.hr": "https://axnro.getonline.ie/wp-content/uploads/2024/10/AXN-hover.png",
    "AXNSpin.hr": "https://axnro.getonline.ie/wp-content/uploads/2024/10/AXN_spin.png",
    "M1Film.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1.png",
    "M1Gold.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1gold.png",
    "M1Family.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1family.svg",
    "SuperstarTV1.rs": "https://superstartv.rs/wp-content/uploads/2024/05/ss1-1.png",
    "SuperstarTV2.rs": "https://superstartv.rs/wp-content/uploads/2024/05/ss2-1.png",
    "SuperstarTV3.rs": "https://superstartv.rs/wp-content/uploads/2024/05/ss3n.png",
    "528074792267": "https://tv-hr-prod.yo-digital.com/prod/images/logos/445/250/c0dfc41344be994e918bde5d6594c0cf.000328.png",  # Hits
    "528074792422": "https://tv-hr-prod.yo-digital.com/prod/images/logos/445/250/0a94c619694dd7c4d7aed031121c739d.000331.png",  # Festival
    "528078376344": "https://tv-hr-prod.yo-digital.com/prod/images/logos/445/250/10a620143bb634323129956f97c6bc82.000329.png",  # Emotion
    "DiziChannel.hr": "https://www.tvprogramdanas.net/uploads/logos/dizi.webp",
}


def download(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (EPG guide)"}), timeout=35) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def text(element, xpath):
    found = element.xpath(xpath)
    return " ".join(found[0].text_content().split()) if found else ""


def timestamp(day, clock, previous=None):
    stamp = datetime.strptime(day + " " + clock, "%Y-%m-%d %H:%M").replace(tzinfo=ZONE)
    if previous is not None and stamp <= previous:
        stamp += timedelta(days=1)
    return stamp


def axn_schedules(page):
    tree = html.fromstring(page)
    groups = {}
    for day in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " day ")][@id]'):
        match = re.fullmatch(r"(\d{4}-\d\d-\d\d)_HRV", day.get("id"))
        if not match:
            continue
        section = day.getparent().getparent().get("class", "")
        channel_id = "AXNSpin.hr" if "et_pb_text_4 " in section else "AXN.hr" if "et_pb_text_3 " in section else None
        if channel_id is None:
            raise ValueError("AXN channel schedule layout changed")
        previous = None
        for program in day.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " program ")]'):
            clock = text(program, './/span[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            title = text(program, './/span[contains(concat(" ", normalize-space(@class), " "), " title ")]')
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title:
                raise ValueError("Incomplete AXN programme")
            start = timestamp(match.group(1), clock, previous)
            previous = start
            description = text(program, './/span[contains(concat(" ", normalize-space(@class), " "), " desc ")]')
            groups.setdefault(channel_id, []).append((start, title, description))
    if set(groups) != {"AXN.hr", "AXNSpin.hr"}:
        raise ValueError("AXN and AXN Spin schedules are both required")
    return groups


def m1_schedule(page):
    tree = html.fromstring(page)
    day_labels = tree.xpath('//ul[contains(concat(" ", normalize-space(@class), " "), " raspored-dani ")]/li')
    day_lists = tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " raspored-pregled ")]/div')
    if not day_labels or len(day_labels) != len(day_lists):
        raise ValueError("M1 schedule days missing or changed")
    programmes = []
    for label, listing in zip(day_labels, day_lists):
        match = re.search(r"\b(\d\d)\.(\d\d)\.(\d{4})\b", label.text_content())
        if not match:
            raise ValueError("M1 schedule date missing")
        day = f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
        previous = None
        for item in listing.xpath('.//ul[contains(concat(" ", normalize-space(@class), " "), " raspored-lista ")]/li'):
            clock = text(item, './/span[contains(concat(" ", normalize-space(@class), " "), " tv-time ")]')
            title = text(item, './a[contains(concat(" ", normalize-space(@class), " "), " left ")]')
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title:
                raise ValueError("Incomplete M1 programme")
            start = timestamp(day, clock, previous)
            previous = start
            programmes.append((start, title, text(item, './/span[contains(@class,"tv-director")]')))
    return programmes


def load_m1_schedule(url):
    # A successful HTTP response can occasionally contain an incomplete EPG page.
    for attempt in range(3):
        try:
            programmes = m1_schedule(download(url))
            if not programmes:
                raise ValueError("M1 schedule contains no programmes")
            return programmes
        except ValueError:
            if attempt == 2:
                print(f"WARNING: M1 schedule unavailable at {url}; continuing without today's M1 programmes")
                return []
            time.sleep(2 * (attempt + 1))


def superstar_schedules(page):
    tree = html.fromstring(page)
    match = re.search(r"(\d\d\.\d\d\.\d{4})\s*[–-]\s*(\d\d\.\d\d\.\d{4})", tree.text_content())
    if not match:
        raise ValueError("Superstar published schedule date range missing")
    first = datetime.strptime(match.group(1), "%d.%m.%Y").date()
    last = datetime.strptime(match.group(2), "%d.%m.%Y").date()
    if last < first or (last - first).days > 14:
        raise ValueError("Unexpected Superstar schedule date range")

    schedules = {}
    for channel_id, tab_id in SUPERSTAR_TABS.items():
        tab = tree.xpath(f'//*[@id="{tab_id}"]')
        if len(tab) != 1:
            raise ValueError(f"Missing official Superstar tab for {channel_id}")
        programmes = []
        seen_days = set()
        for heading in tab[0].xpath('.//h3'):
            date_match = re.search(r"\b(\d\d)\.(\d\d)\b", heading.text_content())
            if not date_match:
                continue
            day = first.replace(day=int(date_match.group(1)), month=int(date_match.group(2)))
            if day < first and first.month == 12:
                day = day.replace(year=first.year + 1)
            if not first <= day <= last or day in seen_days:
                continue  # WordPress repeats the same tables in nested page sections.
            seen_days.add(day)
            table = heading.xpath('ancestor::table[1]')[0]
            previous = None
            for row in table.xpath('./tr[td]'):
                cells = row.xpath('./td')
                if len(cells) < 2:
                    continue
                clock = " ".join(cells[0].text_content().split())
                title = " ".join(cells[1].text_content().split())
                if not re.fullmatch(r"\d\d:\d\d", clock) or not title:
                    raise ValueError(f"Incomplete Superstar listing for {channel_id} on {day}")
                start = timestamp(day.isoformat(), clock, previous)
                previous = start
                programmes.append((start, title, ""))
        if len(seen_days) < 3 or len(programmes) < 20:
            raise ValueError(f"Superstar channel schedule incomplete: {channel_id}")
        if last < datetime.now(ZONE).date() - timedelta(days=1):
            print(f"WARNING: Superstar schedule expired {last}; waiting for publisher's next update")
            programmes = []
        schedules[channel_id] = programmes
    return schedules


def dizi_schedule(page):
    tree = html.fromstring(page)
    entries = []
    dates = set()
    for tab in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " schedule-tab ")]'):
        match = re.fullmatch(r"schedule-(\d{4}-\d\d-\d\d)", tab.get("id", ""))
        if not match:
            raise ValueError("Missing Dizi schedule day")
        day = match.group(1)
        dates.add(day)
        for row in tab.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " timeline-item ")]'):
            clock = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            duration = text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " duration ")]')
            title = text(row, './/h3[contains(concat(" ", normalize-space(@class), " "), " program-name ")]')
            description = text(row, './/p[contains(concat(" ", normalize-space(@class), " "), " program-desc ")]')
            minutes = re.fullmatch(r"(\d+)\s*min", duration)
            if not title or not re.fullmatch(r"\d\d:\d\d", clock) or not minutes:
                raise ValueError(f"Incomplete Dizi programme on {day}")
            start = timestamp(day, clock)
            stop = start + timedelta(minutes=int(minutes.group(1)))
            entries.append((start, title, description, stop))
    if not dates or len(entries) < 10:
        raise ValueError("Dizi channel schedule missing")
    today = datetime.now(ZONE).date()
    if max(dates) < (today - timedelta(days=1)).isoformat():
        print(f"WARNING: Dizi schedule expired {max(dates)}; waiting for publisher's next update")
        return []
    return entries


def append_programmes(root, channel_id, entries):
    entries = sorted(set(entries), key=lambda item: item[0])
    if len(entries) < 10:
        raise ValueError(f"Too few programmes for {channel_id}: {len(entries)}")
    for index, item in enumerate(entries):
        start, title, description = item[:3]
        stop = item[3] if len(item) == 4 else entries[index + 1][0] if index + 1 < len(entries) else start + timedelta(hours=2)
        if not start < stop <= start + timedelta(hours=6):
            raise ValueError(f"Invalid programme times for {channel_id}: {start} -> {stop}")
        event = ET.SubElement(root, "programme", {
            "channel": channel_id,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        })
        ET.SubElement(event, "title", lang="hr").text = title
        if description:
            ET.SubElement(event, "desc", lang="hr").text = description
    print(f"Imported {len(entries)} programmes for {channel_id}")


def main(guide_path, config_path, logo_csv, logos_dir):
    try:
        schedules = axn_schedules(download(AXN_URL))
    except TimeoutError as exc:
        print(f"WARNING: AXN schedule download timed out; continuing without AXN schedules: {exc}")
        schedules = {}
    schedules.update({channel_id: load_m1_schedule(url) for channel_id, url in M1_URLS.items()})
    schedules.update(superstar_schedules(download(SUPERSTAR_URL)))
    schedules["DiziChannel.hr"] = dizi_schedule(download(DIZI_URL))
    config = ET.parse(config_path).getroot()
    custom_ids = {channel.get("xmltv_id") for channel in config}
    if custom_ids != (set(M1_URLS) | {"M1Family.hr", "AXN.hr", "AXNSpin.hr", "DiziChannel.hr"} | set(SUPERSTAR_TABS)):
        raise ValueError("Custom channel configuration differs from logo list")
    if not custom_ids <= set(LOGOS):
        raise ValueError("Missing custom channel logos")

    with logo_csv.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    existing = {row["guide_id"] for row in rows}
    logos_dir.mkdir(parents=True, exist_ok=True)
    for channel_id, url in LOGOS.items():
        filename = "film-" + channel_id.lower().replace(".", "-") + ".png"
        output = logos_dir / filename
        if not output.is_file():
            data = download(url)
            if url.endswith(".svg"):
                if ET.fromstring(data).tag != "{http://www.w3.org/2000/svg}svg":
                    raise ValueError(f"Unexpected logo format: {channel_id}")
                data = cairosvg.svg2png(bytestring=data, output_width=300)
            elif url.endswith(".webp"):
                with Image.open(io.BytesIO(data)) as image:
                    buffer = io.BytesIO()
                    image.convert("RGBA").save(buffer, format="PNG")
                    data = buffer.getvalue()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Unexpected logo format: {channel_id}")
            output.write_bytes(data)
        target_url = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/" + filename
        if channel_id not in existing:
            rows.append({"guide_id": channel_id, "logo_url": target_url})
    with logo_csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    tree = ET.parse(guide_path)
    root = tree.getroot()
    channels = root.findall("channel")
    existing_ids = {channel.get("id") for channel in channels}
    for offset, configured in enumerate(config):
        channel_id = configured.get("xmltv_id")
        if channel_id in existing_ids:
            raise ValueError(f"Duplicate custom channel: {channel_id}")
        node = ET.Element("channel", id=channel_id)
        ET.SubElement(node, "display-name", lang="hr").text = configured.text
        if channel_id == "AXN.hr":
            ET.SubElement(node, "display-name", lang="hr").text = "AXN ADRIA"
        root.insert(len(channels) + offset, node)
    for channel_id, entries in schedules.items():
        if entries:
            append_programmes(root, channel_id, entries)
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Usage: import_film_epg.py guide.xml film-channels.xml logos.csv logos-dir")
    main(*(Path(arg) for arg in sys.argv[1:]))
