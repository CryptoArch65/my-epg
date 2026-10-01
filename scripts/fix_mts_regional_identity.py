#!/usr/bin/env python3
"""Fix identity/logo handling for TV AS, Pester TV and RTV Kraljevo.

TV AS and Pester already have working MTS v2 schedules. Their logos are taken
from the same live MTS v2 product records and copied into this repository so
TiviMate receives stable raw.githubusercontent.com URLs.

RTV Kraljevo is a distinct channel from TV Krusevac. Create a dedicated
RTVKraljevo.rs channel from the live MTS v2 feed and host its MTS logo too.
"""

import copy
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Belgrade")
API = "https://mts.rs/hybris/mtscommercewebservices/v2/mtsB2C/products/search"
RAW_BASE = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos"

LOGO_TARGETS = {
    "TVAS.rs": {
        "code": "tv_as",
        "file": "srb-tv-as.png",
        "aliases": ("TV AS", "tv_as", "as_tv"),
    },
    "PesterTV.rs": {
        "code": "pester_tv",
        "file": "srb-pester-tv.png",
        "aliases": ("Pester TV", "Pešter TV", "pester_tv", "tv_pester"),
    },
}

KRALJEVO = {
    "guide_id": "RTVKraljevo.rs",
    "display": "TV Kraljevo",
    "codes": ("tv_kraljevo", "rtv_kraljevo", "tv_kraljevo_i_ibarske_novosti"),
    "names": ("TV Kraljevo", "TV Kraljevo i ibarske novosti", "RTV Kraljevo"),
    "aliases": ("TV Kraljevo", "RTV Kraljevo", "tv_kraljevo", "rtv_kraljevo"),
    "logo_file": "srb-rtv-kraljevo.png",
}


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
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"})
    with urlopen(req, timeout=40) as response:
        return json.load(response)


def products_for_day(day):
    first = fetch_page(day, 0)
    pages = (first.get("pagination") or {}).get("totalPages", 1)
    if not isinstance(pages, int) or not 1 <= pages <= 50:
        raise ValueError(f"Unexpected MTS v2 pagination: {first.get('pagination')!r}")
    products = list(first.get("products") or [])
    for page in range(1, pages):
        products.extend(fetch_page(day, page).get("products") or [])
    return products


def first_url(value, base=""):
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("//"):
            return "https:" + value
        if value.startswith("http://"):
            return "https://" + value[len("http://"):]
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
        # Prefer primary/logo-like records first.
        ordered = []
        if value.get("imageType") == "PRIMARY":
            ordered.extend(value.get(key) for key in ("url", "src", "path"))
        ordered.extend(value.get(key) for key in ("url", "src", "path", "image", "logo"))
        ordered.extend(value.values())
        for item in ordered:
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
    if not logo:
        return None
    host = (urlparse(logo).hostname or "").lower()
    allowed = (
        host == "mts.rs"
        or host.endswith(".mts.rs")
        or host.endswith(".telekom.rs")
        or host.endswith(".telekomsrbija.com")
    )
    return logo if allowed else None


def find_kraljevo(products):
    wanted_codes = {norm(code) for code in KRALJEVO["codes"]}
    wanted_names = {norm(name) for name in KRALJEVO["names"]}
    for product in products:
        if norm(product.get("code")) in wanted_codes:
            return product
    for product in products:
        if norm(product.get("name")) in wanted_names:
            return product
    candidates = [
        p for p in products
        if "kraljevo" in norm(p.get("name")) and norm(p.get("name")) not in {"katv", "kraljevackatv"}
    ]
    return candidates[0] if len(candidates) == 1 else None


def local_dt(value):
    if not isinstance(value, str) or len(value) < 19:
        raise ValueError(f"Unexpected MTS timestamp: {value!r}")
    return datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=ZONE)


def download_logo(url, filename):
    if not url:
        raise ValueError("MTS product has no usable logo URL")
    logos = Path("logos")
    logos.mkdir(exist_ok=True)
    path = logos / filename
    req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"})
    with urlopen(req, timeout=30) as response:
        data = response.read()
        content_type = str(response.headers.get("Content-Type") or "")
    if len(data) < 100:
        raise ValueError(f"Logo download too small: {url}")
    if "html" in content_type.lower():
        raise ValueError(f"Logo URL returned HTML: {url}")
    path.write_bytes(data)
    print(f"Hosted logo source {url} -> {path} ({len(data)} bytes, {content_type or 'unknown type'})")
    return f"{RAW_BASE}/{filename}"


def set_icon(channel, url):
    for icon in list(channel.findall("icon")):
        channel.remove(icon)
    ET.SubElement(channel, "icon", {"src": url})


def ensure_channel(root, channel_id, display, icon_url=None):
    channels = {c.get("id"): c for c in root.findall("channel")}
    channel = channels.get(channel_id)
    if channel is None:
        channel = ET.Element("channel", {"id": channel_id})
        ET.SubElement(channel, "display-name", {"lang": "sr"}).text = display
        root.insert(len(root.findall("channel")), channel)
    elif display not in [n.text for n in channel.findall("display-name")]:
        ET.SubElement(channel, "display-name", {"lang": "sr"}).text = display
    if icon_url:
        set_icon(channel, icon_url)
    return channel


def sync_alias_metadata(root, source, alias_id, display):
    if alias_id == source.get("id"):
        return
    channels = {c.get("id"): c for c in root.findall("channel")}
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
    if display not in [n.text for n in alias.findall("display-name")]:
        ET.SubElement(alias, "display-name", {"lang": "sr"}).text = display


def add_programme(root, channel_id, item):
    try:
        start = local_dt(item["start"])
        stop = local_dt(item["end"])
    except Exception:
        return None
    title = str(item.get("title") or "").strip()
    if not title or start >= stop:
        return None
    p = ET.SubElement(root, "programme", {
        "channel": channel_id,
        "start": start.strftime("%Y%m%d%H%M%S %z"),
        "stop": stop.strftime("%Y%m%d%H%M%S %z"),
    })
    ET.SubElement(p, "title", {"lang": "sr"}).text = title
    desc = item.get("description")
    if isinstance(desc, str) and desc.strip():
        ET.SubElement(p, "desc", {"lang": "sr"}).text = desc.strip()
    category = item.get("category")
    if isinstance(category, str) and category.strip():
        ET.SubElement(p, "category", {"lang": "sr"}).text = category.strip()
    return p


def main(path):
    tree = ET.parse(path)
    root = tree.getroot()
    channels = {c.get("id"): c for c in root.findall("channel")}

    today = datetime.now(ZONE).date()
    per_day = {}
    for day in (today, today + timedelta(days=1)):
        per_day[day] = products_for_day(day.isoformat())
    today_products = per_day[today]

    # Host logos using the same MTS v2 products that provide the working EPG.
    for channel_id, spec in LOGO_TARGETS.items():
        channel = channels.get(channel_id)
        if channel is None:
            print(f"WARNING: {channel_id} missing; cannot update logo")
            continue
        product = next((p for p in today_products if str(p.get("code") or "") == spec["code"]), None)
        if product is None:
            print(f"WARNING: MTS product {spec['code']!r} missing for {channel_id}")
            continue
        source_logo = product_logo(product)
        try:
            hosted = download_logo(source_logo, spec["file"])
        except Exception as exc:
            print(f"WARNING: could not host MTS logo for {channel_id}: {exc}; source={source_logo!r}")
            continue
        set_icon(channel, hosted)
        for alias_id in spec["aliases"]:
            alias = channels.get(alias_id)
            if alias is not None:
                set_icon(alias, hosted)
        print(f"{channel_id}: hosted MTS logo {hosted}")

    # Create/fix RTV Kraljevo from the live MTS v2 website feed.
    sample = find_kraljevo(today_products)
    if sample is None:
        matches = [(p.get("code"), p.get("name")) for p in today_products if "kralj" in norm(p.get("name"))]
        raise ValueError(f"TV Kraljevo not found in MTS v2; candidates={matches!r}")

    code = str(sample.get("code") or "")
    name = str(sample.get("name") or "")
    items = []
    for day, products in per_day.items():
        product = next((p for p in products if str(p.get("code") or "") == code), None) or find_kraljevo(products)
        if product is not None:
            items.extend(product.get("programs") or [])

    kraljevo_source_logo = product_logo(sample)
    try:
        kraljevo_logo = download_logo(kraljevo_source_logo, KRALJEVO["logo_file"])
    except Exception as exc:
        print(f"WARNING: could not host MTS Kraljevo logo: {exc}; source={kraljevo_source_logo!r}")
        kraljevo_logo = None

    source = ensure_channel(root, KRALJEVO["guide_id"], KRALJEVO["display"], kraljevo_logo)
    target_ids = {KRALJEVO["guide_id"], *KRALJEVO["aliases"]}
    for programme in list(root.findall("programme")):
        if programme.get("channel") in target_ids:
            root.remove(programme)

    added = []
    seen = set()
    for item in items:
        try:
            key = (local_dt(item["start"]), local_dt(item["end"]), str(item.get("title") or "").strip())
        except Exception:
            continue
        if not key[2] or key in seen:
            continue
        seen.add(key)
        p = add_programme(root, KRALJEVO["guide_id"], item)
        if p is not None:
            added.append(p)
    if not added:
        raise ValueError(f"MTS v2 returned no usable programmes for Kraljevo code={code!r} name={name!r}")

    for alias_id in KRALJEVO["aliases"]:
        sync_alias_metadata(root, source, alias_id, KRALJEVO["display"])
        for p in added:
            clone = copy.deepcopy(p)
            clone.set("channel", alias_id)
            root.append(clone)

    tree.write(path, encoding="utf-8", xml_declaration=True)

    now = datetime.now(ZONE)
    current = []
    for p in added:
        start = datetime.strptime(p.get("start"), "%Y%m%d%H%M%S %z").astimezone(ZONE)
        stop = datetime.strptime(p.get("stop"), "%Y%m%d%H%M%S %z").astimezone(ZONE)
        if start <= now < stop:
            current.append(f"{start:%H:%M}-{stop:%H:%M} {p.findtext('title')}")
    print(
        f"RTVKraljevo.rs: MTS code={code!r} name={name!r} programmes={len(added)} "
        f"logo={'yes' if kraljevo_logo else 'no'} current={'; '.join(current) or 'NONE'}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: fix_mts_regional_identity.py guide.xml")
    main(Path(sys.argv[1]))
