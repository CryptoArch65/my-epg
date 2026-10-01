#!/usr/bin/env python3
"""Diagnose MTS regional EPG timestamp semantics and duplicate channel variants."""

from datetime import datetime, timezone
import re
import unicodedata

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


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


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


def compact_meta(product):
    interesting = {}
    for key in (
        "code", "name", "url", "position", "pozicija", "channelPosition",
        "channelType", "serviceType", "platform", "productType", "pk",
    ):
        value = product.get(key)
        if value not in (None, "", [], {}):
            interesting[key] = value
    return interesting


def candidate_products(products, code, display):
    wanted = {normalize(code), normalize(display)}
    rows = []
    for product in products:
        pcode = normalize(product.get("code"))
        pname = normalize(product.get("name"))
        if pcode in wanted or pname in wanted or any(
            token and (token in pcode or token in pname or pcode in token or pname in token)
            for token in wanted
        ):
            rows.append(product)
    return rows


def main():
    now = datetime.now(ZONE)
    day = now.date().isoformat()
    products = day_products(day)
    by_code = {str(product.get("code") or ""): product for product in products}

    print(f"MTS regional timestamp diagnostic now={now.isoformat()} day={day}")
    print(f"Products fetched: {len(products)}")

    for code, display in TARGETS.items():
        print(f"\n=== {display} / code={code} ===")
        candidates = candidate_products(products, code, display)
        print(f"Candidate MTS products: {len(candidates)}")
        for index, candidate in enumerate(candidates, 1):
            programs = candidate.get("programs") or []
            print(f" CANDIDATE {index}: {compact_meta(candidate)!r}; programs={len(programs)}")
            for item in programs[:8]:
                try:
                    local_start = existing_interpretation(item.get("start"))
                    local_stop = existing_interpretation(item.get("end"))
                    local_label = f"{local_start:%H:%M}-{local_stop:%H:%M}"
                except Exception:
                    local_label = "?"
                print(
                    "   ITEM:", local_label,
                    repr(item.get("start")), "->", repr(item.get("end")), "|", title(item)
                )

        product = by_code.get(code)
        if product is None:
            print("Exact-code product NOT FOUND")
            continue
        programs = product.get("programs") or []
        print(f"Selected exact-code product name={product.get('name')!r}; programs={len(programs)}")
        if not programs:
            continue

        current, previous, upcoming = current_item(programs, existing_interpretation, now)
        print(" EXISTING parser:")
        describe("CURRENT", current)
        describe("PREVIOUS", previous)
        describe("NEXT", upcoming)

        current, previous, upcoming = current_item(programs, utc_if_naive_interpretation, now)
        print(" ALT parser:")
        describe("CURRENT", current)
        describe("PREVIOUS", previous)
        describe("NEXT", upcoming)


if __name__ == "__main__":
    main()
