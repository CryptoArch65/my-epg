#!/usr/bin/env python3
"""Cache official Hrvatski Telekom MAXSport logos for XMLTV clients."""

import csv
import sys
from pathlib import Path
from urllib.request import Request, urlopen


LOGOS = {
    "311616552052": ("1", "https://www.hrvatskitelekom.hr/webresources/images/maxtv-new/programi/250x250_maxsport1.png"),
    "311620648169": ("2", "https://www.hrvatskitelekom.hr/webresources/images/maxtv-new/programi/250x250_maxsport2.png"),
}
REPO_LOGO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/maxsport-{}.png"


def main(logos_csv, logos_dir):
    with logos_csv.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["guide_id", "logo_url"]:
            raise ValueError("Unexpected channel logo CSV header")
        rows = list(reader)

    by_id = {row["guide_id"]: row for row in rows}
    if set(LOGOS) - set(by_id):
        raise ValueError("Missing MAXSport source channel logo mappings")
    if all(by_id[guide_id]["logo_url"] == REPO_LOGO.format(number)
           and (logos_dir / f"maxsport-{number}.png").is_file()
           for guide_id, (number, _) in LOGOS.items()):
        print("Both official MAXSport logos already hosted in the repository")
        return

    downloads = {}
    for guide_id, (number, url) in LOGOS.items():
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.hrvatskitelekom.hr/"})
        with urlopen(request, timeout=30) as response:
            data = response.read(1_000_001)
        if not data.startswith(b"\x89PNG\r\n\x1a\n") or len(data) > 1_000_000:
            raise ValueError(f"Invalid official MAXSport {number} logo")
        downloads[guide_id] = data
        print(f"Downloaded official MAXSport {number} logo ({len(data)} bytes)")

    logos_dir.mkdir(parents=True, exist_ok=True)
    for guide_id, data in downloads.items():
        number = LOGOS[guide_id][0]
        (logos_dir / f"maxsport-{number}.png").write_bytes(data)
        by_id[guide_id]["logo_url"] = REPO_LOGO.format(number)
    with logos_csv.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_maxsport_logos.py config/bih-source-logos.csv logos/")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
