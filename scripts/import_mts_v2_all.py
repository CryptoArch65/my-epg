#!/usr/bin/env python3
"""Replace every MTS-backed schedule in an existing XMLTV guide with the
current MTS website v2 feed.

The live mts.rs website uses mtscommercewebservices/v2 and returns programme
clock values labelled +0000 even though the site displays those values as
Europe/Belgrade wall-clock times. Preserve the wall clock and attach the
Belgrade timezone explicitly.

Only channels already present in the guide are changed. Existing channel
metadata/logos are preserved. Known playlist aliases are mirrored so TiviMate
sees the same schedule regardless of which tvg-id is used.
"""

import copy
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Belgrade")
API = "https://mts.rs/hybris/mtscommercewebservices/v2/mtsB2C/products/search"

XML_CONFIGS = (
    Path("config/channels.xml"),
    Path("config/serbia-extra-mts.xml"),
    Path("config/hype-mts.xml"),
    Path("config/informer-mts.xml"),
)
PINK_CSV = Path("config/pink-mts-channels.csv")
PLAYLIST_ALIASES = Path("config/playlist_aliases.csv")

# Extra Serbian channels handled by the custom regional importer.  Keeping
# aliases here ensures the tested v2 schedule reaches the IDs used by TiviMate.
REGIONALS = (
    ("TVIstok.rs", "tv_istok", "TV Istok 1", ("TV Istok", "tv_istok")),
    ("TVLeskovac.rs", "tv_leskovac", "TV Leskovac", ("TV Leskovac", "tv_leskovac")),
    ("JefimijaTV.rs", "TV Jefimija", "TV Jefimija", ("TV Jefimija", "TV%20Jefimija")),
    ("TVKrusevac.rs", "tv_krusevac", "TV Kruševac", ("TV Kruševac", "tv_krusevac")),
    ("NewsmaxBalkans.rs", "Newsmax_Balkans", "Newsmax Balkans", ("Newsmax_Balkans", "Newsmax Balkans", "newsmaxbalkans.rs")),
    ("TVAS.rs", "tv_as", "TV AS", ("TV AS", "tv_as", "as_tv")),
    ("TVBor.rs", "tv_bor", "TV Bor", ("tv_bor", "TV Bor", "101TV.rs")),
    ("SOSKanalPlus.rs", "sos_kanal_plus", "SOS Kanal Plus", ("sos_kanal_plus", "SOS Kanal Plus")),
    ("PesterTV.rs", "pester_tv", "Pešter TV", ("pester_tv", "tv_pester", "Pešter TV", "Pester TV")),
)


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def fetch_page(day, page):
    query = f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}"
    url = API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 50,
        "fields": "FULL",
        "currentPage": page,
    })
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    })
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def products_for_day(day):
    first = fetch_page(day, 0)
    pagination = first.get("pagination") or {}
    pages = pagination.get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS v2 pagination on {day}: {pagination!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        data = fetch_page(day, page)
        if data.get("pagination", {}).get("currentPage") != page:
            raise ValueError(f"Unexpected MTS v2 page {page} on {day}")
        products.extend(data.get("products") or [])
    print(f"MTS v2 {day}: {len(products)} products across {pages} pages")
    return products


def local_dt(value):
    if not isinstance(value, str) or len(value) < 19:
        raise ValueError(f"Unexpected MTS v2 timestamp: {value!r}")
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE)


def local_stamp(value):
    return local_dt(value).strftime("%Y%m%d%H%M%S %z")


def load_mappings():
    mappings = {}

    def add(guide_id, code, display="", aliases=()):
        guide_id = str(guide_id or "").strip()
        code = unquote(str(code or "").strip())
        if not guide_id or not code:
            return
        row = mappings.setdefault(guide_id, {
            "guide_id": guide_id,
            "code": code,
            "display": display or guide_id,
            "aliases": set(),
        })
        if row["code"] != code:
            print(f"WARNING: conflicting MTS codes for {guide_id}: {row['code']!r} vs {code!r}; keeping first")
        row["aliases"].update(a for a in aliases if a and a != guide_id)

    for path in XML_CONFIGS:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        for channel in root.findall("channel"):
            if channel.get("site") != "mts.rs":
                continue
            add(channel.get("xmltv_id"), channel.get("site_id"), "".join(channel.itertext()).strip())

    if PINK_CSV.exists():
        with PINK_CSV.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                add(row.get("guide_id"), row.get("mts_site_id"), row.get("channel_name"))

    for guide_id, code, display, aliases in REGIONALS:
        add(guide_id, code, display, aliases)

    # Mirror canonical MTS schedules onto playlist tvg-id aliases generated by
    # add_playlist_aliases.py when those aliases are present in the final guide.
    if PLAYLIST_ALIASES.exists():
        with PLAYLIST_ALIASES.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                guide_id = row.get("guide_id", "").strip()
                alias = row.get("playlist_tvg_id", "").strip()
                if guide_id in mappings and alias and alias != guide_id:
                    mappings[guide_id]["aliases"].add(alias)

    return mappings


def find_product(products, code, display):
    exact = next((p for p in products if unquote(str(p.get("code", ""))) == code), None)
    if exact is not None:
        return exact
    wanted_code = norm(code)
    exact = next((p for p in products if norm(unquote(str(p.get("code", "")))) == wanted_code), None)
    if exact is not None:
        return exact
    wanted_name = norm(display)
    return next((p for p in products if wanted_name and norm(p.get("name")) == wanted_name), None)


def add_programme(root, channel_id, item):
    try:
        start_dt = local_dt(item["start"])
        stop_dt = local_dt(item["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if start_dt >= stop_dt:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None

    programme = ET.SubElement(
        root,
        "programme",
        channel=channel_id,
        start=start_dt.strftime("%Y%m%d%H%M%S %z"),
        stop=stop_dt.strftime("%Y%m%d%H%M%S %z"),
    )
    ET.SubElement(programme, "title", lang="sr").text = title
    description = item.get("description")
    if isinstance(description, str) and description.strip():
        ET.SubElement(programme, "desc", lang="sr").text = description.strip()
    category = item.get("category")
    if isinstance(category, str) and category.strip():
        ET.SubElement(programme, "category", lang="sr").text = category.strip()
    picture = item.get("picture")
    if isinstance(picture, dict) and picture.get("url"):
        ET.SubElement(programme, "image").text = str(picture["url"])
    return programme


def replace_schedule(root, guide_id, aliases, items):
    channels = {c.get("id"): c for c in root.findall("channel")}
    source_channel = channels.get(guide_id)
    if source_channel is None:
        return 0, []

    active_aliases = [alias for alias in aliases if alias in channels and alias != guide_id]
    target_ids = {guide_id, *active_aliases}
    for programme in list(root.findall("programme")):
        if programme.get("channel") in target_ids:
            root.remove(programme)

    source_programmes = []
    for item in items:
        programme = add_programme(root, guide_id, item)
        if programme is not None:
            source_programmes.append(programme)

    for alias in active_aliases:
        for programme in source_programmes:
            clone = copy.deepcopy(programme)
            clone.set("channel", alias)
            root.append(clone)

    return len(source_programmes), active_aliases


def main(path):
    mappings = load_mappings()
    tree = ET.parse(path)
    root = tree.getroot()
    existing_channels = {c.get("id") for c in root.findall("channel")}
    active = {gid: row for gid, row in mappings.items() if gid in existing_channels}
    print(f"MTS v2 mappings present in this guide: {len(active)}/{len(mappings)}")

    today = datetime.now(ZONE).date()
    days = (today, today + timedelta(days=1))
    per_day = {day: products_for_day(day.isoformat()) for day in days}

    updated = 0
    unavailable = []
    diagnostics = {}
    for guide_id, row in active.items():
        items = []
        product_name = ""
        matched_code = row["code"]
        for day in days:
            product = find_product(per_day[day], row["code"], row["display"])
            if product is None:
                continue
            product_name = product_name or str(product.get("name") or "")
            matched_code = str(product.get("code") or matched_code)
            items.extend(product.get("programs") or [])

        # Do not destroy a working fallback schedule when MTS has no data.
        usable = []
        seen = set()
        for item in items:
            try:
                key = (local_stamp(item["start"]), local_stamp(item["end"]), str(item.get("title") or "").strip())
            except Exception:
                continue
            if not key[2] or key in seen:
                continue
            seen.add(key)
            usable.append(item)
        if not usable:
            unavailable.append(guide_id)
            print(f"WARNING: MTS v2 has no usable programmes for {guide_id} code={row['code']!r}; keeping existing schedule")
            continue

        count, aliases = replace_schedule(root, guide_id, row["aliases"], usable)
        if count:
            updated += 1
            print(
                f"MTS v2 {guide_id}: code={matched_code!r}, name={product_name!r}, "
                f"programmes={count}, aliases={','.join(sorted(aliases)) or '-'}"
            )
            if guide_id in {"RTS1.rs", "B92.rs", "Pink.rs", "AgroTV.rs", "HypeTV.rs", "TVKrusevac.rs"}:
                diagnostics[guide_id] = usable

    tree.write(path, encoding="utf-8", xml_declaration=True)
    print(f"MTS v2 updated {updated}/{len(active)} present channels; unavailable={len(unavailable)}")
    if unavailable:
        print("MTS v2 unavailable (existing schedules preserved): " + ", ".join(sorted(unavailable)))

    now = datetime.now(ZONE)
    print(f"MTS v2 control diagnostics now={now.isoformat()}")
    for guide_id, items in diagnostics.items():
        current = []
        for item in items:
            try:
                start, stop = local_dt(item["start"]), local_dt(item["end"])
            except Exception:
                continue
            if start <= now < stop:
                current.append((start, stop, str(item.get("title") or "")))
        text = "; ".join(f"{a:%H:%M}-{b:%H:%M} {title}" for a, b, title in current) or "NO CURRENT PROGRAMME"
        print(f"  {guide_id}: {text}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: import_mts_v2_all.py guide.xml")
    main(Path(sys.argv[1]))
