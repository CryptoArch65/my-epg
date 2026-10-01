#!/usr/bin/env python3
"""Supplement Serbian EPG entries that need special MTS/alias handling.

- K1: keep the official/existing guide schedule, then fill any uncovered gaps
  from every MTS API page.
- Serbian regional/local channels: use the complete MTS API result instead of
  the standard grabber path that can return 0 programmes for these channels.
- Balkan Trip: keep the working m:tel schedule exposed under its provider alias.
"""

import copy
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from import_mts_pink_epg import ZONE, day_products, stamp

K1_ID = "K1.rs"
K1_ALIASES = ("k1-tv", "k1_duplicate")
K1_CODES = ("k1_hd", "k1_duplicate")

BALKAN_SOURCE_ID = "iptv#ch-461-balkan-trip-hd"
BALKAN_ALIAS_ID = "Balkan Trip"

REGIONAL_TARGETS = (
    {
        "guide_id": "TVIstok.rs",
        "display": "TV Istok 1",
        "codes": ("tv_istok",),
        "names": ("TV Istok", "TV Istok 1"),
        "aliases": ("TV Istok", "tv_istok"),
    },
    {
        "guide_id": "TVLeskovac.rs",
        "display": "TV Leskovac",
        "codes": ("tv_leskovac",),
        "names": ("TV Leskovac", "Televizija Leskovac"),
        "aliases": ("TV Leskovac", "tv_leskovac"),
    },
    {
        "guide_id": "JefimijaTV.rs",
        "display": "TV Jefimija",
        "codes": ("TV Jefimija", "TV%20Jefimija"),
        "names": ("TV Jefimija", "Jefimija TV", "Jefimija"),
        "aliases": ("TV Jefimija", "TV%20Jefimija"),
    },
    {
        "guide_id": "TVKrusevac.rs",
        "display": "TV Kruševac",
        "codes": ("tv_krusevac",),
        "names": ("TV Kruševac", "TV Krusevac", "RTK Kruševac"),
        "aliases": ("TV Kruševac", "tv_krusevac"),

        "clock_offset_hours": -2,    },
    {
        "guide_id": "NewsmaxBalkans.rs",
        "display": "Newsmax Balkans",
        "codes": ("Newsmax_Balkans", "newsmax_balkans"),
        "names": ("Newsmax Balkans", "Newsmax Balkans HD", "Newsmax"),
        "aliases": ("Newsmax_Balkans", "Newsmax Balkans", "newsmaxbalkans.rs"),

        "clock_offset_hours": -2,    },
    {
        "guide_id": "TVAS.rs",
        "display": "TV AS",
        "codes": ("tv_as", "as_tv"),
        "names": ("TV AS", "AS TV", "Televizija AS"),
        "aliases": ("TV AS", "tv_as", "as_tv"),
    },
    {
        "guide_id": "TVBor.rs",
        "display": "TV Bor",
        "codes": ("tv_bor",),
        "names": ("TV Bor", "BOR TV", "RTV Bor"),
        "aliases": ("tv_bor", "TV Bor", "101TV.rs"),
    },
    {
        "guide_id": "SOSKanalPlus.rs",
        "display": "SOS Kanal Plus",
        "codes": ("sos_kanal_plus",),
        "names": ("SOS Kanal Plus", "SOS Plus"),
        "aliases": ("sos_kanal_plus", "SOS Kanal Plus"),

        "clock_offset_hours": -2,    },
    {
        "guide_id": "PesterTV.rs",
        "display": "Pešter TV",
        "codes": ("pester_tv", "tv_pester", "pester"),
        "names": ("Pešter TV", "Pester TV", "TV Pešter", "TV Pester"),
        "aliases": ("pester_tv", "tv_pester", "Pešter TV", "Pester TV"),

        "clock_offset_hours": -2,    },
)


def regional_stamp(value, offset_hours=0):
    """Interpret an MTS regional clock as Serbia local time plus a safe override.

    MTS appends ``Z`` to regional programme times even when the visible clock is
    already Europe/Belgrade local time. A few channels are additionally two
    hours late in MTS itself; ``offset_hours`` corrects only those channels.
    """
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            local = __import__("datetime").datetime.fromisoformat(text[:-1])
            if local.tzinfo is not None:
                local = local.replace(tzinfo=None)
            local = local.replace(tzinfo=ZONE)
            if offset_hours:
                local = local + timedelta(hours=offset_hours)
            return local.strftime("%Y%m%d%H%M%S %z")
    parsed = parse_xmltv_time(stamp(value)).astimezone(ZONE)
    if offset_hours:
        parsed = parsed + timedelta(hours=offset_hours)
    return parsed.strftime("%Y%m%d%H%M%S %z")


def parse_xmltv_time(value):
    return datetime.strptime(value, "%Y%m%d%H%M%S %z")


def programme_interval(programme):
    try:
        return parse_xmltv_time(programme.get("start")), parse_xmltv_time(programme.get("stop"))
    except (TypeError, ValueError):
        return None


def overlaps(start, stop, intervals):
    return any(start < other_stop and other_start < stop for other_start, other_stop in intervals)


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def product_name(product):
    for key in ("name", "title", "channelName"):
        value = product.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def first_url(value, base=""):
    if isinstance(value, str):
        if value.startswith("https://"):
            return value
        if base and value.startswith("/"):
            return urljoin(base, value)
        return None
    if isinstance(value, list):
        for item in value:
            url = first_url(item, base)
            if url:
                return url
    if isinstance(value, dict):
        for key in ("url", "src", "path", "image", "logo"):
            if key in value:
                url = first_url(value[key], base)
                if url:
                    return url
        for item in value.values():
            url = first_url(item, base)
            if url:
                return url
    return None


def product_logo(product):
    logo = (
        first_url(product.get("picture"), "https://mts.rs")
        or first_url(product.get("images"), "https://mts.rs")
        or first_url(product.get("logo"), "https://mts.rs")
    )
    if logo and urlparse(logo).hostname in {
        "mts.rs", "www.mts.rs", "medias.services.mts.rs", "mediasb2c.mts.rs"
    }:
        return logo
    return None


def add_item(root, channel_id, start, stop, item):
    programme = ET.SubElement(root, "programme", channel=channel_id, start=start, stop=stop)
    ET.SubElement(programme, "title", lang="sr").text = item["title"].strip()

    description = item.get("description")
    if isinstance(description, str) and description.strip():
        ET.SubElement(programme, "desc", lang="sr").text = description.strip()

    category = item.get("category")
    if isinstance(category, str) and category.strip():
        ET.SubElement(programme, "category", lang="sr").text = category.strip()
    elif isinstance(category, list):
        for value in category:
            if isinstance(value, str) and value.strip():
                ET.SubElement(programme, "category", lang="sr").text = value.strip()

    picture = item.get("picture")
    if isinstance(picture, dict):
        image = picture.get("url")
        if isinstance(image, str) and image.strip():
            ET.SubElement(programme, "image").text = image.strip()

    return programme


def ensure_channel(root, channel_id, display, template=None, logo=None):
    channels = {node.get("id"): node for node in root.findall("channel")}
    channel = channels.get(channel_id)
    if channel is None:
        if template is not None:
            channel = copy.deepcopy(template)
            channel.set("id", channel_id)
        else:
            channel = ET.Element("channel", {"id": channel_id})
            ET.SubElement(channel, "display-name", {"lang": "sr"}).text = display
        root.insert(len(root.findall("channel")), channel)

    names = [node.text for node in channel.findall("display-name")]
    if display not in names:
        ET.SubElement(channel, "display-name", {"lang": "sr"}).text = display

    if logo:
        for icon in list(channel.findall("icon")):
            channel.remove(icon)
        ET.SubElement(channel, "icon", {"src": logo})
    return channel


def sync_alias(root, source_id, alias_id, display=None):
    if alias_id == source_id:
        return
    channels = {node.get("id"): node for node in root.findall("channel")}
    source = channels[source_id]
    alias = channels.get(alias_id)
    if alias is None:
        alias = copy.deepcopy(source)
        alias.set("id", alias_id)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source:
            alias.append(copy.deepcopy(child))
    if display:
        names = [node.text for node in alias.findall("display-name")]
        if display not in names:
            ET.SubElement(alias, "display-name", {"lang": "sr"}).text = display

    for programme in list(root.findall("programme")):
        if programme.get("channel") == alias_id:
            root.remove(programme)
    for programme in root.findall("programme"):
        if programme.get("channel") == source_id:
            clone = copy.deepcopy(programme)
            clone.set("channel", alias_id)
            root.append(clone)


def match_product(products, target):
    wanted_codes = {normalize(unquote(code)) for code in target["codes"]}
    wanted_names = {normalize(name) for name in target["names"]}

    for product in products:
        if normalize(unquote(str(product.get("code", "")))) in wanted_codes:
            return product
    for product in products:
        name = normalize(product_name(product))
        if name in wanted_names:
            return product
    # Last resort: tolerate HD/TV suffix/prefix differences while avoiding very short matches.
    for product in products:
        name = normalize(product_name(product))
        if not name:
            continue
        for wanted in wanted_names:
            if len(wanted) >= 6 and (name.startswith(wanted) or wanted.startswith(name)):
                return product
    return None


def import_regionals(root):
    today = datetime.now(ZONE).date()
    per_day = {}
    try:
        for day in (today, today + timedelta(days=1)):
            per_day[day] = day_products(day.isoformat())
    except Exception as exc:
        print(f"WARNING: MTS regional import unavailable; keeping existing schedules: {exc}")
        return {}

    results = {}
    all_products = per_day[today]
    for target in REGIONAL_TARGETS:
        guide_id = target["guide_id"]
        sample = match_product(all_products, target)
        if sample is None:
            print(f"WARNING: MTS regional channel not found: {target['display']}")
            results[guide_id] = 0
            continue

        code = str(sample.get("code", ""))
        logo = product_logo(sample)
        items = {}
        matched_names = []
        for day, products in per_day.items():
            product = next(
                (row for row in products if str(row.get("code", "")) == code),
                None,
            ) or match_product(products, target)
            if product is None:
                continue
            matched_names.append(product_name(product))
            for item in product.get("programs") or []:
                title = item.get("title")
                if not isinstance(title, str) or not title.strip():
                    continue
                try:
                    start = regional_stamp(item["start"], target.get("clock_offset_hours", 0))
                    stop = regional_stamp(item["end"], target.get("clock_offset_hours", 0))
                    if parse_xmltv_time(start) >= parse_xmltv_time(stop):
                        continue
                except (KeyError, TypeError, ValueError):
                    continue
                items[(start, stop, title.strip())] = item

        channels = {node.get("id"): node for node in root.findall("channel")}
        template = channels.get(guide_id)
        if template is None:
            for alias in target["aliases"]:
                if alias in channels:
                    template = channels[alias]
                    break
        ensure_channel(root, guide_id, target["display"], template=template, logo=logo)

        if items:
            ids_to_clear = {guide_id, *target["aliases"], code, unquote(code)}
            for programme in list(root.findall("programme")):
                if programme.get("channel") in ids_to_clear:
                    root.remove(programme)
            for (start, stop, _title), item in sorted(items.items()):
                add_item(root, guide_id, start, stop, item)

            aliases = list(target["aliases"])
            for alias in (code, unquote(code)):
                if alias and alias not in aliases and alias != guide_id:
                    aliases.append(alias)
            for alias in aliases:
                sync_alias(root, guide_id, alias, target["display"])

        results[guide_id] = len(items)
        print(
            f"MTS regional {guide_id}: code={code!r}, name={product_name(sample)!r}, "
            f"programmes={len(items)}, logo={'yes' if logo else 'no'}"
        )
    return results


def supplement_k1(root):
    channels = {channel.get("id") for channel in root.findall("channel")}
    if K1_ID not in channels:
        print(f"WARNING: {K1_ID} is missing; cannot supplement K1")
        return 0

    today = datetime.now(ZONE).date()
    candidates = []
    seen = set()
    per_code = {code: 0 for code in K1_CODES}

    try:
        for day in (today, today + timedelta(days=1)):
            products = day_products(day.isoformat())
            by_code = {product.get("code"): product for product in products}
            for code in K1_CODES:
                product = by_code.get(code)
                if product is None:
                    continue
                for item in product.get("programs") or []:
                    title = item.get("title")
                    if not isinstance(title, str) or not title.strip():
                        continue
                    try:
                        start = stamp(item["start"])
                        stop = stamp(item["end"])
                        start_dt = parse_xmltv_time(start)
                        stop_dt = parse_xmltv_time(stop)
                    except (KeyError, TypeError, ValueError) as exc:
                        print(f"WARNING: skipping malformed K1 MTS item: {exc}")
                        continue
                    if start_dt >= stop_dt:
                        continue
                    key = (start, stop, title.strip())
                    if key in seen:
                        continue
                    seen.add(key)
                    per_code[code] += 1
                    candidates.append((start_dt, stop_dt, start, stop, item, code))
    except Exception as exc:
        print(f"WARNING: MTS K1 supplement unavailable; keeping existing K1 schedule: {exc}")
        return 0

    existing = [p for p in root.findall("programme") if p.get("channel") == K1_ID]
    intervals = []
    for programme in existing:
        interval = programme_interval(programme)
        if interval is not None:
            intervals.append(interval)

    aliases = [alias for alias in K1_ALIASES if alias in channels]
    added = 0
    for start_dt, stop_dt, start, stop, item, code in sorted(candidates, key=lambda row: (row[0], K1_CODES.index(row[5]))):
        if overlaps(start_dt, stop_dt, intervals):
            continue

        programme = add_item(root, K1_ID, start, stop, item)
        for alias in aliases:
            alias_programme = copy.deepcopy(programme)
            alias_programme.set("channel", alias)
            root.append(alias_programme)

        intervals.append((start_dt, stop_dt))
        added += 1

    print(
        "K1 MTS supplement: "
        f"existing={len(existing)}, "
        f"mts_k1_hd={per_code['k1_hd']}, "
        f"mts_k1_duplicate={per_code['k1_duplicate']}, "
        f"gap_fill_added={added}, aliases={','.join(aliases) or 'none'}"
    )

    now = datetime.now(ZONE)
    current = 0
    for programme in root.findall("programme"):
        if programme.get("channel") != K1_ID:
            continue
        interval = programme_interval(programme)
        if interval is not None and interval[0] <= now < interval[1]:
            current += 1
    print(f"K1 current programme coverage after supplement: {current}")
    return added


def sync_balkan_alias(root):
    channels = {channel.get("id"): channel for channel in root.findall("channel")}
    source = channels.get(BALKAN_SOURCE_ID)
    if source is None:
        print(f"WARNING: Balkan Trip source {BALKAN_SOURCE_ID} is missing")
        return 0

    alias = channels.get(BALKAN_ALIAS_ID)
    if alias is None:
        alias = copy.deepcopy(source)
        alias.set("id", BALKAN_ALIAS_ID)
        root.insert(len(root.findall("channel")), alias)
    else:
        for child in list(alias):
            alias.remove(child)
        for child in source:
            alias.append(copy.deepcopy(child))

    names = [node.text for node in alias.findall("display-name")]
    if "|SRB| BALKAN TRIP" not in names:
        ET.SubElement(alias, "display-name", lang="sr").text = "|SRB| BALKAN TRIP"

    for programme in list(root.findall("programme")):
        if programme.get("channel") == BALKAN_ALIAS_ID:
            root.remove(programme)

    source_programmes = [
        programme for programme in root.findall("programme")
        if programme.get("channel") == BALKAN_SOURCE_ID
    ]
    for programme in source_programmes:
        alias_programme = copy.deepcopy(programme)
        alias_programme.set("channel", BALKAN_ALIAS_ID)
        root.append(alias_programme)

    print(f"Balkan Trip alias {BALKAN_ALIAS_ID}: {len(source_programmes)} programmes copied from {BALKAN_SOURCE_ID}")
    return len(source_programmes)


def main(guide_path):
    tree = ET.parse(guide_path)
    root = tree.getroot()

    supplement_k1(root)
    import_regionals(root)
    sync_balkan_alias(root)

    tree.write(guide_path, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_serbia_epg.py guide.xml")
    main(Path(sys.argv[1]))
