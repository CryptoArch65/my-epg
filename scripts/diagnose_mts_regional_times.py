#!/usr/bin/env python3
"""Diagnose MTS regional EPG source variants against the public website schedule."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import re
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from import_mts_pink_epg import API, ZONE, day_products, stamp

TARGETS = {
    "tv_istok": "TV Istok 1",
    "tv_krusevac": "TV Krusevac",
    "tv_bor": "TV Bor",
    "sos_kanal_plus": "SOS Kanal Plus",
    "Newsmax_Balkans": "Newsmax Balkans",
    "tv_as": "TV AS",
    "pester_tv": "Pester TV",
}

QUERY_VARIANTS = {
    "legacy-tv-kanali": lambda day: f":pozicija-rastuce:tip-kanala-radio:TV kanali:channelProgramDates:{day}",
    "website-iris-tv-paketi": lambda day: f":pozicija-rastuce:tv-kategorija:iris-tv-paketi:channelProgramDates:{day}",
    "website-no-platform-facet": lambda day: f":pozicija-rastuce:channelProgramDates:{day}",
}


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def existing_interpretation(value):
    return datetime.strptime(stamp(value), "%Y%m%d%H%M%S %z").astimezone(ZONE)


def title(item):
    return str(item.get("title") or "(no title)").strip()


def fetch_variant_page(day, query, page):
    url = API + "?" + urlencode({
        "sort": "pozicija-rastuce",
        "searchQueryContext": "CHANNEL_PROGRAM",
        "query": query,
        "pageSize": 10000,
        "currentPage": page,
    })
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=35) as response:
        return json.load(response)


def variant_products(day, query):
    first = fetch_variant_page(day, query, 0)
    pagination = first.get("pagination") or {}
    pages = pagination.get("totalPages")
    if not isinstance(pages, int) or not 1 <= pages <= 30:
        raise ValueError(f"Unexpected MTS pagination: {pagination!r}")
    products = list(first.get("products") or [])
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(fetch_variant_page, day, query, page): page for page in range(1, pages)}
        for job in as_completed(jobs):
            data = job.result()
            products.extend(data.get("products") or [])
    return products


def product_by_code(products, code):
    return next((p for p in products if str(p.get("code") or "") == code), None)


def print_schedule(label, product):
    if product is None:
        print(f"  {label}: NOT FOUND")
        return
    programs = product.get("programs") or []
    print(
        f"  {label}: code={product.get('code')!r} name={product.get('name')!r} "
        f"position={product.get('channelPosition')!r} programs={len(programs)}"
    )
    for item in programs:
        try:
            start = existing_interpretation(item.get("start"))
            stop = existing_interpretation(item.get("end"))
        except Exception:
            continue
        if 12 <= start.hour <= 16 or 12 <= stop.hour <= 16:
            print(f"    {start:%H:%M}-{stop:%H:%M} | {title(item)} | raw={item.get('start')!r}")


def main():
    now = datetime.now(ZONE)
    day = now.date().isoformat()
    print(f"MTS query-facet diagnostic now={now.isoformat()} day={day}")

    variants = {}
    for label, query_builder in QUERY_VARIANTS.items():
        query = query_builder(day)
        try:
            products = variant_products(day, query)
        except Exception as exc:
            print(f"VARIANT {label}: FAILED: {exc}")
            continue
        variants[label] = products
        print(f"VARIANT {label}: products={len(products)} query={query}")

    for code, display in TARGETS.items():
        print(f"\n=== {display} / {code} ===")
        for label, products in variants.items():
            print_schedule(label, product_by_code(products, code))

    # Keep one duplicate/near-name diagnostic from the legacy response as a sanity check.
    products = variants.get("legacy-tv-kanali") or day_products(day)
    for code, display in TARGETS.items():
        wanted = {normalize(code), normalize(display)}
        matches = []
        for product in products:
            pcode = normalize(product.get("code"))
            pname = normalize(product.get("name"))
            if pcode in wanted or pname in wanted:
                matches.append(product)
        print(f"EXACT/NORMALIZED candidates {display}: {[(p.get('code'), p.get('name'), p.get('channelPosition')) for p in matches]}")


if __name__ == "__main__":
    main()
