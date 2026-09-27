#!/usr/bin/env python3
"""Add AXN and M1 schedules and their broadcasters' logos to the XMLTV guide."""

import csv
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


ZONE = ZoneInfo("Europe/Zagreb")
AXN_URL = "https://axn.hr/program-tv/"
M1_URLS = {
    "M1Film.hr": "https://www.m1film.hr/hr/epg/",
    "M1Gold.hr": "https://www.m1film.hr/gold/epg/",
}
LOGOS = {
    "AXN.hr": "https://axnro.getonline.ie/wp-content/uploads/2024/10/AXN-hover.png",
    "AXNSpin.hr": "https://axnro.getonline.ie/wp-content/uploads/2024/10/AXN_spin.png",
    "M1Film.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1.png",
    "M1Gold.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1gold.png",
    "M1Family.hr": "https://www.m1film.hr/system/template/mediatv/images/logo-m1family.svg",
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


def append_programmes(root, channel_id, entries):
    entries = sorted(set(entries), key=lambda item: item[0])
    if len(entries) < 10:
        raise ValueError(f"Too few programmes for {channel_id}: {len(entries)}")
    for index, (start, title, description) in enumerate(entries):
        stop = entries[index + 1][0] if index + 1 < len(entries) else start + timedelta(hours=2)
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
    schedules = axn_schedules(download(AXN_URL))
    schedules.update({channel_id: m1_schedule(download(url)) for channel_id, url in M1_URLS.items()})
    config = ET.parse(config_path).getroot()
    if {channel.get("xmltv_id") for channel in config} != set(LOGOS):
        raise ValueError("Custom channel configuration differs from logo list")

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
        append_programmes(root, channel_id, entries)
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        raise SystemExit("Usage: import_film_epg.py guide.xml film-channels.xml logos.csv logos-dir")
    main(*(Path(arg) for arg in sys.argv[1:]))
