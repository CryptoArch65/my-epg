#!/usr/bin/env python3
"""Diagnose MTS regional EPG timestamp semantics against Europe/Belgrade now."""

from datetime import datetime, timezone

from import_mts_pink_epg import ZONE, day_products, stamp

TARGETS = {
    "tv_istok": "TV Istok 1",
    "tv_krusevac": "TV Krusevac",
    "tv_bor": "TV Bor",
    "sos_kanal_plus": "SOS Kanal Plus",
    "Newsmax_Balkans": "Newsmax Balkans",
    "tv_as": "TV AS",
    "pester_tv": "Pester TV",
}


def existing_interpretation(value):
    return datetime.strptime(stamp(value), "%Y%m%d%H%M%S %z").astimezone(ZONE)


def utc_if_naive_interpretation(value):
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, timezone.utc).astimezone(ZONE)
    if not isinstance(value, str):
        raise ValueError(f"Unexpected timestamp: {value!r}")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZONE)


def title(item):
    return str(item.get("title") or "(no title)").strip()


def current_item(programs, parser, now):
    rows = []
    for item in programs:
        try:
            start = parser(item.get("start"))
            stop = parser(item.get("end"))
        except Exception:
            continue
        rows.append((start, stop, item))
    rows.sort(key=lambda row: row[0])
    current = next((row for row in rows if row[0] <= now < row[1]), None)
    previous = max((row for row in rows if row[1] <= now), default=None, key=lambda row: row[1])
    upcoming = min((row for row in rows if row[0] > now), default=None, key=lambda row: row[0])
    return current, previous, upcoming


def describe(label, row):
    if row is None:
        print(f"  {label}: NONE")
        return
    start, stop, item = row
    print(f"  {label}: {start.isoformat()} -> {stop.isoformat()} | {title(item)}")


def main():
    now = datetime.now(ZONE)
    day = now.date().isoformat()
    products = day_products(day)
    by_code = {str(product.get("code") or ""): product for product in products}

    print(f"MTS regional timestamp diagnostic now={now.isoformat()} day={day}")
    print(f"Products fetched: {len(products)}")

    for code, display in TARGETS.items():
        product = by_code.get(code)
        print(f"\n=== {display} / code={code} ===")
        if product is None:
            print("NOT FOUND")
            continue
        programs = product.get("programs") or []
        print(f"MTS name={product.get('name')!r}; programs={len(programs)}")
        if not programs:
            continue

        for item in programs[:3]:
            print(
                "  RAW sample:",
                repr(item.get("start")), "->", repr(item.get("end")), "|", title(item)
            )

        current, previous, upcoming = current_item(programs, existing_interpretation, now)
        print(" EXISTING parser (naive => Europe/Belgrade):")
        describe("CURRENT", current)
        describe("PREVIOUS", previous)
        describe("NEXT", upcoming)

        current, previous, upcoming = current_item(programs, utc_if_naive_interpretation, now)
        print(" ALT parser (naive => UTC, then Europe/Belgrade):")
        describe("CURRENT", current)
        describe("PREVIOUS", previous)
        describe("NEXT", upcoming)


if __name__ == "__main__":
    main()
