#!/usr/bin/env python3
"""Match provider channel names against TVProfil and build runtime importer config."""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

BOX_URL = "https://tvprofil.com/box/"
QUALITY = {"hd", "fhd", "uhd", "4k", "8k", "sd", "hevc", "h265", "h264", "1080p", "720p", "2160p"}
COUNTRY_PREFIX = re.compile(r"^\s*\|(?:bih|bh|ba|hr|srb|sr|rs)\|\s*", re.I)


def strip_diacritics(value: str) -> str:
    value = (value or "").replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


@lru_cache(maxsize=None)
def normalize(value: str) -> str:
    s = strip_diacritics(value).lower()
    s = COUNTRY_PREFIX.sub("", s)
    s = re.sub(r"\(src\d+\)", " ", s)
    s = re.sub(r"[①②③④⑤⑥⑦⑧⑨⑩➀➁➂➃➄➅➆➇➈➉❶❷❸❹❺❻❼❽❾❿]", " ", s)
    s = re.sub(r"[^a-z0-9+]+", " ", s)
    tokens = [t for t in s.split() if t not in QUALITY]
    return " ".join(tokens)


def safe_id(tvg_id: str, corrected_name: str) -> str:
    if tvg_id:
        return tvg_id
    base = normalize(corrected_name).replace(" ", ".")[:48] or "channel"
    digest = hashlib.sha1(corrected_name.encode("utf-8")).hexdigest()[:8]
    return f"tvprofil.{base}.{digest}"


def load_overrides(path: Path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {
            row["provider_name"].strip(): row
            for row in csv.DictReader(f)
            if row.get("provider_name", "").strip()
        }


def extract_catalog(page):
    raw = page.evaluate(r"""
    () => {
      const out = [];
      const attrs = ['data-kanal','data-channel','data-slug','data-id','value','href'];
      const clean = s => (s || '').replace(/\s+/g, ' ').trim();
      for (const el of document.querySelectorAll('a,input,option,[data-kanal],[data-channel],[data-slug]')) {
        let name = clean(el.textContent);
        if (!name && el.labels && el.labels.length) name = clean(el.labels[0].textContent);
        if (!name) name = clean(el.getAttribute('title'));
        if (!name) name = clean(el.getAttribute('aria-label'));
        const values = {};
        for (const a of attrs) values[a] = el.getAttribute(a) || '';
        out.push({name, values});
      }
      return {items: out, html: document.documentElement.innerHTML};
    }
    """)
    found = {}

    def add(name, slug):
        name = " ".join((name or "").split()).strip()
        slug = unquote((slug or "").strip()).strip("/")
        if not name or not slug or slug.isdigit() or len(slug) > 160:
            return
        if "/" in slug:
            match = re.search(r"/tvprogram/(?:program/)?kanal/([^/?#]+)", "/" + slug)
            if match:
                slug = match.group(1)
            else:
                return
        if not re.search(r"[a-zA-Z]", slug):
            return
        found[(name, slug)] = {"name": name, "slug": slug}

    for item in raw["items"]:
        name = item.get("name", "")
        for value in item.get("values", {}).values():
            if not value:
                continue
            match = re.search(r"/tvprogram/(?:program/)?kanal/([^/?#]+)", value)
            if match:
                add(name, match.group(1))
            elif re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", value):
                add(name, value)

    html = raw.get("html", "")
    patterns = [
        r'"(?:name|title|label)"\s*:\s*"([^"]{2,100})".{0,180}?"(?:slug|kanal|channel)"\s*:\s*"([a-zA-Z][a-zA-Z0-9_-]{2,})"',
        r'"(?:slug|kanal|channel)"\s*:\s*"([a-zA-Z][a-zA-Z0-9_-]{2,})".{0,180}?"(?:name|title|label)"\s*:\s*"([^"]{2,100})"',
    ]
    for index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, html, re.S):
            if index == 0:
                add(match.group(1), match.group(2))
            else:
                add(match.group(2), match.group(1))

    return list(found.values())


def best_match(name: str, catalog):
    key = normalize(name)
    exact = [candidate for candidate in catalog if normalize(candidate["name"]) == key]
    if len(exact) == 1:
        return exact[0], "matched", 1.0
    if len(exact) > 1:
        return exact[0], "ambiguous", 1.0

    scored = sorted(
        ((difflib.SequenceMatcher(None, key, normalize(candidate["name"])).ratio(), candidate) for candidate in catalog),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored:
        return None, "not_found", 0.0
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.92 and best_score - second >= 0.06:
        return best, "matched", best_score
    if best_score >= 0.72:
        return best, "ambiguous", best_score
    return None, "not_found", best_score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", default="config/tvprofil_playlist_channels.csv")
    parser.add_argument("--overrides", default="config/tvprofil_name_overrides.csv")
    parser.add_argument("--base-config", default="config/tvprofil_channels.json")
    parser.add_argument("--output-config", default="config/tvprofil_channels.runtime.json")
    parser.add_argument("--report", default="config/tvprofil_playlist_channels.csv")
    parser.add_argument("--catalog", help="JSON catalog exported from a TvProfil browser session")
    args = parser.parse_args()

    channels_path = Path(args.channels)
    with channels_path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    overrides = load_overrides(Path(args.overrides))

    if args.catalog:
        catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        if not isinstance(catalog, list) or any(
            not isinstance(item, dict) or not item.get("name") or not (item.get("slug") or item.get("id"))
            for item in catalog
        ):
            raise SystemExit("Catalog must be a JSON array of {name, slug} or {name, id} entries")
    else:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page(locale="hr-HR", timezone_id="Europe/Zagreb")
            page.goto(BOX_URL, wait_until="load", timeout=60000)
            catalog = extract_catalog(page)
            if not catalog:
                print("TVProfil page:", page.url, page.title())
                print("TVProfil controls:", page.evaluate("() => [...document.querySelectorAll('input, option, label, a')].slice(0, 12).map(e => e.outerHTML.slice(0, 300))"))
                raise SystemExit("Could not extract TVProfil channel catalog from /box/")
            browser.close()
    print(f"TVProfil catalog candidates: {len(catalog)}")

    output = []
    fields = list(rows[0].keys()) if rows else []
    for needed in ["corrected_name", "tvprofil_name", "tvprofil_id", "tvprofil_slug", "status", "confidence", "note"]:
        if needed not in fields:
            fields.append(needed)

    for row in rows:
        provider = row.get("provider_name", "").strip()
        override = overrides.get(provider, {})
        corrected = (override.get("corrected_name") or row.get("corrected_name") or provider).strip()
        manual_slug = (override.get("tvprofil_slug") or (row.get("tvprofil_slug") if row.get("status") == "manual" else "") or "").strip()
        manual_name = (override.get("tvprofil_name") or (row.get("tvprofil_name") if row.get("status") == "manual" else "") or "").strip()
        enabled = override.get("enabled", "yes").strip().lower() not in {"0", "no", "false", "off"}

        row["corrected_name"] = corrected
        if not enabled:
            row.update(status="disabled", confidence="", note="disabled by manual override")
            continue

        if manual_slug:
            candidate = {"name": manual_name or corrected, "slug": manual_slug}
            status, score = "manual", 1.0
        else:
            candidate, status, score = best_match(manual_name or corrected, catalog)

        if candidate:
            row["tvprofil_name"] = candidate["name"]
            row["tvprofil_id"] = candidate.get("id", "")
            row["tvprofil_slug"] = candidate.get("slug", "")
            if status == "matched" and not candidate.get("slug"):
                status = "needs_slug"
        else:
            row["tvprofil_name"] = ""
            row["tvprofil_id"] = ""
            row["tvprofil_slug"] = ""
        row["status"] = status
        row["confidence"] = f"{score:.3f}" if score else ""
        row["note"] = "manual override" if status == "manual" else row.get("note", "")

        if status in {"matched", "manual"} and candidate:
            output.append({
                "xmltv_id": safe_id(row.get("tvg_id", "").strip(), corrected),
                "slug": candidate["slug"],
                "display_name": corrected,
            })

    with Path(args.report).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    base = []
    base_path = Path(args.base_config)
    if base_path.exists():
        base = json.loads(base_path.read_text(encoding="utf-8"))
    merged = {channel["xmltv_id"]: channel for channel in base}
    for channel in output:
        merged[channel["xmltv_id"]] = channel
    Path(args.output_config).write_text(
        json.dumps(list(merged.values()), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("Match status:", counts)
    print(f"Runtime TVProfil channels: {len(merged)} -> {args.output_config}")


if __name__ == "__main__":
    main()
