#!/usr/bin/env python3
"""Host selected Serbian regional logos in the repository for XMLTV clients."""
import csv
import io
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin
from lxml import html
from PIL import Image

TARGETS = {
    "SandzakTV.rs": (
        "https://logos.siptvs.com/EXYU/SRBIJA/SANDZAK.png",
        "https://trefoil.tv/uploads/posts/2023-11/sandzak-tv.webp",
        "page:https://sandzak.tv/",
    ),
    "TVIstok.rs": (
        "https://logos.siptvs.com/EXYU/GENERAL/tvistok.png",
        "https://www.nsz.gov.rs/storage/images/75059-logo-tv-istok-photo.jpg",
    ),
    "TVLeskovac.rs": (
        "https://logos.siptvs.com/EXYU/full/LESKOVAC.png",
        "page:https://www.tvl.rs/",
    ),
    "TVKrusevac.rs": (
        "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/serbia/rtk-krusevac-rs.png",
        "https://www.rtk.rs/wp-content/uploads/2024/06/LOGO-RTK-Krusevac.jpg",
    ),
    "JefimijaTV.rs": (
        "https://logos.siptvs.com/EXYU/full/jefimija.png",
        "page:https://jefimija.tv/",
    ),
}
REPO = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"

def main(csv_file, logos_dir):
    with csv_file.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    by_id = {row["guide_id"]: row for row in rows}
    if not set(TARGETS) <= set(by_id):
        raise ValueError("Regional logo mappings missing")
    logos_dir.mkdir(parents=True, exist_ok=True)
    for guide_id, sources in TARGETS.items():
        target = logos_dir / ("serbia-" + guide_id.lower().replace(".", "-") + ".png")
        if not target.is_file():
            for source in sources:
                if source.startswith("page:"):
                    try:
                        page = source[5:]
                        request = Request(page, headers={"User-Agent": "Mozilla/5.0"})
                        with urlopen(request, timeout=25) as response:
                            doc = html.fromstring(response.read(2_000_000))
                        matches = []
                        for img in doc.xpath("//img"):
                            attrs = " ".join(str(v) for v in img.attrib.values()).lower()
                            if "logo" in attrs or any(term in attrs for term in ("sandzak", "jefimija", "leskovac")):
                                matches.append((img.get("alt"), img.get("src") or img.get("data-src")))
                        print(f"Logo candidates on {page}: {matches[:12]}")
                    except Exception as exc:
                        print(f"Cannot inspect {source}: {exc}")
                    continue
                try:
                    request = Request(source, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
                    with urlopen(request, timeout=25) as response:
                        data = response.read(2_000_001)
                    if len(data) > 2_000_000:
                        raise ValueError("Image too large")
                    with Image.open(io.BytesIO(data)) as image:
                        if image.width > 3000 or image.height > 3000:
                            raise ValueError("Image dimensions too large")
                        output = io.BytesIO()
                        image.convert("RGBA").save(output, format="PNG")
                    target.write_bytes(output.getvalue())
                    print(f"Hosted {guide_id} from {source}")
                    break
                except Exception as exc:
                    print(f"Logo unavailable for {guide_id} at {source}: {exc}")
        if target.is_file():
            by_id[guide_id]["logo_url"] = REPO + target.name
        else:
            print(f"Warning: no hosted logo for {guide_id}; retaining existing URL")
    with csv_file.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: host_serbian_local_logos.py logos.csv logos/")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
