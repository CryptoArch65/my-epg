#!/usr/bin/env python3
"""Extract channel metadata from an M3U playlist without storing stream URLs."""
from __future__ import annotations

import argparse
import csv
import io
import re
import urllib.request
from pathlib import Path

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def read_text(source: str) -> str:
    if source.startswith(("http://", "https://")):
        try:
            req = urllib.request.Request(source, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            raise SystemExit(f"Could not download provider M3U: {type(exc).__name__}") from None
    return Path(source).read_text(encoding="utf-8", errors="replace")


def parse_m3u(text: str):
    rows = []
    for line in io.StringIO(text):
        line = line.strip()
        if not line.startswith("#EXTINF:"):
            continue
        head, sep, display_name = line.partition(",")
        if not sep:
            continue
        attrs = dict(ATTR_RE.findall(head))
        name = display_name.strip()
        if not name:
            continue
        rows.append({
            "provider_name": name,
            "group": attrs.get("group-title", "").strip(),
            "tvg_id": attrs.get("tvg-id", "").strip(),
            "tvg_name": attrs.get("tvg-name", "").strip(),
            "tvg_logo": attrs.get("tvg-logo", "").strip(),
        })
    return rows


def load_existing(path: Path):
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        return {
            row.get("provider_name", ""): row
            for row in csv.DictReader(f)
            if row.get("provider_name")
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", help="Local M3U path or HTTPS URL")
    parser.add_argument("--output", default="config/tvprofil_playlist_channels.csv")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing(output)
    rows = parse_m3u(read_text(args.source))
    if not rows:
        raise SystemExit("No #EXTINF channels were found in the M3U")

    fields = [
        "provider_name", "corrected_name", "group", "tvg_id", "tvg_name", "tvg_logo",
        "tvprofil_name", "tvprofil_slug", "status", "confidence", "note",
    ]
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            old = existing.get(row["provider_name"], {})
            corrected = old.get("corrected_name") or row["provider_name"]
            writer.writerow({
                **row,
                "corrected_name": corrected,
                "tvprofil_name": old.get("tvprofil_name", ""),
                "tvprofil_slug": old.get("tvprofil_slug", ""),
                "status": old.get("status", "pending"),
                "confidence": old.get("confidence", ""),
                "note": old.get("note", ""),
            })

    print(f"Extracted {len(rows)} channels -> {output}")
    print("Stream URLs were not written to disk.")


if __name__ == "__main__":
    main()
