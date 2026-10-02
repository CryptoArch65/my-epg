#!/usr/bin/env python3
"""Import/fix the user-requested channels without corrupting shared provider IDs.

Sources:
- NOVA MAX (actual stream is NIŠtv): MTS v2, canonical NisTV.rs
- OSJECKA TV: tvprogramdanas.net schedule + logo
- HRT International: TVEpg.eu rendered page, canonical htv5
- PINK 2 RED: Naslovi.net Red schedule + logo, playlist ID pink2.rs
- Jabuka TV provider mistake: display alias on existing OTV.hr schedule
- RTV Mlava: official logo on canonical RTVMlava.rs
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import html
from playwright.sync_api import sync_playwright

HR_TZ = ZoneInfo("Europe/Zagreb")
RS_TZ = ZoneInfo("Europe/Belgrade")

MTS_API = "https://mts.rs/hybris/mtscommercewebservices/v2/mtsB2C/products/search"
OSJECKA_URL = "https://www.tvprogramdanas.net/osjeka-tv"
OSJECKA_LOGO = "https://www.tvprogramdanas.net/uploads/logos/osjeka-tv.webp"
HRT_INT_URL = "https://tvepg.eu/hr/croatia/channel/hrt_international"
RED_BASE = "https://naslovi.net/tv-program/red"
RED_LOGO = "https://nstatic.net/img/tv/channels/m/red.png"
MLAVA_LOGO = "https://rtvmlava.com/wp-content/uploads/2021/01/rtvmlava-logo.png"


def download(url: str, limit: int = 4_000_000) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (EPG guide)",
                    "Accept-Language": "hr-HR,hr;q=0.9,sr;q=0.8,en;q=0.6",
                },
            )
            with urlopen(req, timeout=40) as response:
                return response.read(limit)
        except Exception as exc:
            last = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise last


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def add_display_name(channel: ET.Element, name: str, lang: str = "") -> None:
    existing = {(node.text or "").strip() for node in channel.findall("display-name")}
    if name in existing:
        return
    attrs = {"lang": lang} if lang else {}
    ET.SubElement(channel, "display-name", attrs).text = name


def channel(root: ET.Element, channel_id: str, names: tuple[str, ...], lang: str = "") -> ET.Element:
    node = next((c for c in root.findall("channel") if c.get("id") == channel_id), None)
    if node is None:
        node = ET.Element("channel", {"id": channel_id})
        root.insert(len(root.findall("channel")), node)
    for name in names:
        add_display_name(node, name, lang)
    return node


def set_icon(node: ET.Element, url: str) -> None:
    for icon in list(node.findall("icon")):
        node.remove(icon)
    ET.SubElement(node, "icon", {"src": url})


def remove_programmes(root: ET.Element, channel_id: str) -> None:
    for item in list(root.findall("programme")):
        if item.get("channel") == channel_id:
            root.remove(item)


def add_programme(
    root: ET.Element,
    channel_id: str,
    start: datetime,
    stop: datetime,
    title: str,
    lang: str,
    desc: str = "",
    category: str = "",
) -> bool:
    if stop <= start or not title.strip():
        return False
    item = ET.SubElement(
        root,
        "programme",
        {
            "channel": channel_id,
            "start": start.strftime("%Y%m%d%H%M%S %z"),
            "stop": stop.strftime("%Y%m%d%H%M%S %z"),
        },
    )
    ET.SubElement(item, "title", {"lang": lang}).text = title.strip()
    if desc.strip():
        ET.SubElement(item, "desc", {"lang": lang}).text = desc.strip()
    if category.strip():
        ET.SubElement(item, "category", {"lang": lang}).text = category.strip()
    return True


def mts_page(day: str, page: int) -> dict:
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = MTS_API + "?" + urlencode(
        {
            "sort": "pozicija-rastuce",
            "searchQueryContext": "CHANNEL_PROGRAM",
            "query": query,
            "pageSize": 50,
            "fields": "FULL",
            "currentPage": page,
        }
    )
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def mts_products(day: str) -> list[dict]:
    first = mts_page(day, 0)
    pages = (first.get("pagination") or {}).get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS pagination: {first.get('pagination')!r}")
    products = list(first.get("products") or [])
    for page_no in range(1, pages):
        products.extend(mts_page(day, page_no).get("products") or [])
    return products


def mts_local(value: str) -> datetime:
    # MTS website v2 labels the timestamps +0000 although their clock portion
    # is displayed as Serbia local wall time. Keep that tested behaviour.
    return datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=RS_TZ)


def import_nis_tv(root: ET.Element) -> int:
    guide_id = "NisTV.rs"
    today = datetime.now(RS_TZ).date()
    programs: list[dict] = []
    source_name = ""
    source_code = ""
    for day in (today, today + timedelta(days=1)):
        products = mts_products(day.isoformat())
        product = next(
            (
                p
                for p in products
                if str(p.get("code") or "") == "NIŠtv"
                or norm(p.get("name")) == "nistv"
                or norm(p.get("code")) == "nistv"
            ),
            None,
        )
        if product is None:
            continue
        source_name = source_name or str(product.get("name") or "")
        source_code = source_code or str(product.get("code") or "")
        programs.extend(product.get("programs") or [])

    unique: dict[tuple[str, str, str], tuple[datetime, datetime, str, str, str]] = {}
    for item in programs:
        try:
            start = mts_local(item["start"])
            stop = mts_local(item["end"])
        except Exception:
            continue
        title = str(item.get("title") or "").strip()
        if not title or stop <= start:
            continue
        desc = str(item.get("description") or "").strip()
        category = str(item.get("category") or "").strip()
        unique[(start.isoformat(), stop.isoformat(), title)] = (start, stop, title, desc, category)

    rows = sorted(unique.values(), key=lambda row: row[0])
    if len(rows) < 3:
        raise ValueError(f"MTS NIŠtv returned only {len(rows)} usable programmes")

    ch = channel(root, guide_id, ("NOVA MAX", "NIŠtv"), "sr")
    remove_programmes(root, guide_id)
    written = sum(add_programme(root, guide_id, *row, "sr") for row in rows)
    print(f"NOVA MAX/Niš TV: MTS code={source_code!r} name={source_name!r}, programmes={written}")
    return written


def node_text(node, xpath: str) -> str:
    found = node.xpath(xpath)
    return " ".join(found[0].text_content().split()) if found else ""


def import_osjecka(root: ET.Element) -> int:
    page = download(OSJECKA_URL)
    tree = html.fromstring(page)
    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    if not canonical or urlparse(canonical[0]).path.rstrip("/") != "/osjeka-tv":
        raise ValueError("Unexpected Osječka TV page")

    today = datetime.now(HR_TZ).date()
    events: dict[datetime, tuple[int, str, str, str]] = {}
    for tab in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " schedule-tab ")]'):
        match = re.fullmatch(r"schedule-(\d{4}-\d\d-\d\d)", tab.get("id", ""))
        if not match:
            continue
        day = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if not today - timedelta(days=1) <= day <= today + timedelta(days=5):
            continue
        for row in tab.xpath('.//div[contains(concat(" ", normalize-space(@class), " "), " timeline-item ")]'):
            clock = node_text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            duration = node_text(row, './/span[contains(concat(" ", normalize-space(@class), " "), " duration ")]')
            title = node_text(row, './/h3[contains(concat(" ", normalize-space(@class), " "), " program-name ")]')
            minutes = re.fullmatch(r"(\d+)\s*min", duration)
            if not re.fullmatch(r"\d\d:\d\d", clock) or not title or not minutes:
                continue
            start = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(tzinfo=HR_TZ)
            desc = node_text(row, './/p[contains(concat(" ", normalize-space(@class), " "), " program-desc ")]')
            category = node_text(row, './/*[contains(concat(" ", normalize-space(@class), " "), " category ")]')
            events[start] = (min(int(minutes.group(1)), 720), title, desc, category)

    starts = sorted(events)
    if len(starts) < 3:
        raise ValueError(f"Osječka TV returned only {len(starts)} current programmes")

    guide_id = "OsječkaTV.hr"
    ch = channel(root, guide_id, ("OSJECKA TV", "Osječka TV"), "hr")
    set_icon(ch, OSJECKA_LOGO)
    remove_programmes(root, guide_id)

    written = 0
    for index, start in enumerate(starts):
        minutes, title, desc, category = events[start]
        stop = start + timedelta(minutes=minutes)
        if index + 1 < len(starts):
            stop = min(stop, starts[index + 1])
        written += add_programme(root, guide_id, start, stop, title, "hr", desc, category)
    print(f"Osječka TV: programmes={written}, logo={OSJECKA_LOGO}")
    return written


def tvepg_events(page: bytes | str) -> list[tuple[datetime, str]]:
    tree = html.fromstring(page)
    events: list[tuple[datetime, str]] = []
    current_day = None
    day_events: list[tuple[datetime, str]] = []

    def flush():
        nonlocal day_events
        if current_day and day_events:
            if len(day_events) > 1 and day_events[0][0].hour >= 20 and day_events[1][0].hour < 6:
                day_events = day_events[1:]
            events.extend(day_events)
        day_events = []

    for node in tree.iter():
        if node.tag in {"h4", "h5", "h6"}:
            heading = " ".join(node.text_content().split())
            match = re.search(r"(\d{2})\.\s*(\d{2})\.\s*(\d{4})", heading)
            if match:
                flush()
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
        if hour > 23 or minute > 59 or not title:
            continue
        start = datetime(current_day.year, current_day.month, current_day.day, hour, minute, tzinfo=HR_TZ)
        day_events.append((start, title))
    flush()

    unique: dict[datetime, str] = {}
    for start, title in events:
        unique.setdefault(start, title)
    today = datetime.now(HR_TZ).date()
    return [(s, unique[s]) for s in sorted(unique) if today - timedelta(days=1) <= s.date() <= today + timedelta(days=7)]


def import_hrt_int(root: ET.Element) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="hr-HR", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/152 Safari/537.36")
        response = page.goto(HRT_INT_URL, wait_until="domcontentloaded", timeout=60000)
        if response is None or response.status >= 400:
            browser.close()
            raise ValueError(f"TVEpg HRT International returned status {response.status if response else 'none'}")
        page.wait_for_timeout(2000)
        rendered = page.content()
        browser.close()

    events = tvepg_events(rendered)
    if len(events) < 3:
        raise ValueError(f"TVEpg HRT International returned only {len(events)} programmes")

    guide_id = "htv5"
    channel(root, guide_id, ("HRT International", "|HR| HRT INT"), "hr")
    remove_programmes(root, guide_id)
    written = 0
    for index, (start, title) in enumerate(events):
        stop = events[index + 1][0] if index + 1 < len(events) else start + timedelta(hours=1)
        if stop - start > timedelta(hours=12):
            stop = start + timedelta(hours=1)
        written += add_programme(root, guide_id, start, stop, title, "hr")
    print(f"HRT International: TVEpg programmes={written}")
    return written


def import_red(root: ET.Element) -> int:
    today = datetime.now(RS_TZ).date()
    events: dict[datetime, tuple[str, str, str]] = {}
    for offset in range(3):
        day = today + timedelta(days=offset)
        url = f"{RED_BASE}/{day.isoformat()}"
        tree = html.fromstring(download(url))
        rows = tree.cssselect("div.tvrow") if hasattr(tree, "cssselect") else []
        if not rows:
            rows = tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " tvrow ")]')
        day_offset = 0
        previous = None
        for row in rows:
            clock = node_text(row, './/*[contains(concat(" ", normalize-space(@class), " "), " time ")]')
            title = node_text(row, './/*[contains(concat(" ", normalize-space(@class), " "), " title ")]')
            if not re.fullmatch(r"\d{1,2}:\d{2}", clock) or not title or title.lower() == "no information":
                continue
            hour, minute = map(int, clock.split(":"))
            current_minutes = hour * 60 + minute
            if previous is not None and current_minutes < previous:
                day_offset += 1
            previous = current_minutes
            start_day = day + timedelta(days=day_offset)
            start = datetime(start_day.year, start_day.month, start_day.day, hour, minute, tzinfo=RS_TZ)
            desc = node_text(row, './/*[contains(concat(" ", normalize-space(@class), " "), " descr ")]')
            category = node_text(row, './/*[contains(concat(" ", normalize-space(@class), " "), " category ")]')
            events[start] = (title, desc, category)

    starts = sorted(events)
    if len(starts) < 3:
        raise ValueError(f"Naslovi Red returned only {len(starts)} programmes")

    guide_id = "pink2.rs"
    ch = channel(root, guide_id, ("PINK 2 RED", "Red TV"), "sr")
    set_icon(ch, RED_LOGO)
    remove_programmes(root, guide_id)
    written = 0
    for index, start in enumerate(starts):
        title, desc, category = events[start]
        stop = starts[index + 1] if index + 1 < len(starts) else start + timedelta(hours=1)
        if stop - start > timedelta(hours=12):
            stop = start + timedelta(hours=1)
        written += add_programme(root, guide_id, start, stop, title, "sr", desc, category)
    print(f"PINK 2 RED: Naslovi programmes={written}, logo={RED_LOGO}")
    return written


def apply_identity_aliases(root: ET.Element) -> None:
    # Jabuka is actually the OTV stream; do not touch DomaTV.hr because that
    # provider ID is also used by the real Doma TV channels.
    otv = channel(root, "OTV.hr", ("OTV", "OTv", "HR: JABUKA TV"), "hr")
    print("Jabuka TV: added display alias HR: JABUKA TV to OTV.hr")

    # RTV Mlava currently arrives with the same provider ID as real RTV Kruševac.
    # Keep a separate canonical channel so assigning it cannot corrupt Kruševac.
    mlava = channel(root, "RTVMlava.rs", ("|SRB| RTV MLAVA", "RTV Mlava"), "sr")
    set_icon(mlava, MLAVA_LOGO)
    print(f"RTV Mlava: official logo={MLAVA_LOGO}")


def main(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()

    import_nis_tv(root)
    import_osjecka(root)

    # TVEpg occasionally blocks plain HTTP clients, so use Chromium. If it is
    # temporarily unavailable, keep any previous working HRT INT schedule.
    try:
        import_hrt_int(root)
    except Exception as exc:
        print(f"WARNING: HRT International TVEpg import failed; preserving prior schedule: {exc!r}")

    import_red(root)
    apply_identity_aliases(root)

    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)

    # Final evidence for the workflow log.
    counts = {}
    for cid in ("NisTV.rs", "OsječkaTV.hr", "htv5", "pink2.rs", "OTV.hr", "RTVMlava.rs"):
        counts[cid] = sum(1 for p in root.findall("programme") if p.get("channel") == cid)
        ch = next((c for c in root.findall("channel") if c.get("id") == cid), None)
        icon = ch.find("icon").get("src") if ch is not None and ch.find("icon") is not None else ""
        names = [(n.text or "").strip() for n in ch.findall("display-name")] if ch is not None else []
        print(f"FINAL {cid}: programmes={counts[cid]} names={names} logo={'yes' if icon else 'no'}")

    for required in ("NisTV.rs", "OsječkaTV.hr", "pink2.rs"):
        if counts[required] < 3:
            raise SystemExit(f"Required channel {required} has only {counts[required]} programmes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_requested_channels.py guide.xml")
    main(Path(sys.argv[1]))
