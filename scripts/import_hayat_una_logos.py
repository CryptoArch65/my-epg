#!/usr/bin/env python3
"""Cache Hayat and m:tel UNA TV channel logos as stable PNG links."""

import csv
import sys
from pathlib import Path
from urllib.request import Request, urlopen


LOGOS = {
    "HayatLoveBox.ba": (
        "hayat-love-box.png",
        "https://static.wikia.nocookie.net/logopedia/images/0/0c/Hayat_Love_Box_-_Logo.png?format=original",
    ),
    "HayatZivotIStil.ba": (
        "hayat-stil-i-zivot.png",
        "https://static.wikia.nocookie.net/logopedia/images/d/de/Hayat_Stil_i_%C5%BEivot_-_Logo.png?format=original",
    ),
    "UnaTV.ba": (
        "una-tv-hd.png",
        "https://medias.services.mtel.ba/medias/una-logo-HD.png?context=bWFzdGVyfHJvb3R8MTQyMjZ8aW1hZ2UvcG5nfGFETmpMMmhsWWk4Mk5qQXpPVGszTWpJMk5qQXhOQzkxYm1GZmJHOW5iMTlJUkM1d2JtY3wyNTZkZGUyM2UwMDdhOThmMmYzNjM0ZTM5OWU5MWYzZjBkMWJhNGZkOTBkYjVjMmQwZjAxN2MwMWU2OGQwY2U5",
    ),
}
REPO_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"


def main(logos_csv, logos_dir):
    with logos_csv.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["guide_id", "logo_url"]:
            raise ValueError("Unexpected channel logo CSV header")
        rows = list(reader)
    by_id = {row["guide_id"]: row for row in rows}
    logos_dir.mkdir(parents=True, exist_ok=True)

    for guide_id, (filename, url) in LOGOS.items():
        target = logos_dir / filename
        if not target.is_file():
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=45) as response:
                data = response.read(1_000_001)
            if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 1_000_000:
                raise ValueError(f"Invalid PNG logo for {guide_id}")
            target.write_bytes(data)
            print(f"Downloaded {guide_id} logo ({len(data)} bytes)")
        logo_url = REPO_LOGO + filename
        if guide_id in by_id:
            by_id[guide_id]["logo_url"] = logo_url
        else:
            row = {"guide_id": guide_id, "logo_url": logo_url}
            rows.append(row)
            by_id[guide_id] = row

    with logos_csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_hayat_una_logos.py config/bih-source-logos.csv logos/")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
