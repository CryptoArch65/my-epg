#!/usr/bin/env python3
"""Trial replacement of Pink and Elita channel logos from a supplied M3U snapshot."""
import csv
import hashlib
import io
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from PIL import Image

RAW_BASE = "https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/"


def fetch(source, target):
    if target.is_file():
        return True, "cached"
    parts = urlsplit(source)
    safe_url = urlunsplit((parts.scheme, parts.netloc, quote(parts.path), parts.query, parts.fragment))
    last_error = None
    for _ in range(2):
        try:
            request = Request(safe_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*"})
            with urlopen(request, timeout=20) as response:
                data = response.read(3_000_001)
            if len(data) > 3_000_000:
                raise ValueError("logo exceeds 3 MB")
            with Image.open(io.BytesIO(data)) as image:
                if image.width * image.height > 25_000_000:
                    raise ValueError("logo dimensions too large")
                converted = image.convert("RGBA")
                converted.thumbnail((1024, 1024))
                output = io.BytesIO()
                converted.save(output, format="PNG")
            target.write_bytes(output.getvalue())
            return True, f"hosted {len(output.getvalue())} bytes"
        except Exception as exc:
            last_error = exc
    return False, str(last_error)


def main(manifest, logos_csv, logos_dir):
    with manifest.open(encoding="utf-8", newline="") as file:
        trial = list(csv.DictReader(file))
    columns = {"guide_id", "m3u_channel", "logo_url", "previous_logo_url"}
    if not trial or any(set(row) != columns for row in trial):
        raise ValueError("Invalid Pink logo trial manifest")
    ids = [row["guide_id"] for row in trial]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate Pink guide ID")
    with logos_csv.open(encoding="utf-8", newline="") as file:
        existing = list(csv.DictReader(file))
    by_id = {row["guide_id"]: row for row in existing}
    logos_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        url: logos_dir / ("m3u-pink-" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".png")
        for url in {row["logo_url"] for row in trial}
    }
    results = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {pool.submit(fetch, url, target): url for url, target in targets.items()}
        for job in as_completed(jobs):
            url = jobs[job]
            results[url] = job.result()
            print(f"Pink M3U logo {url}: {results[url][1]}")
    replaced, unavailable = 0, []
    for row in trial:
        guide_id, url = row["guide_id"], row["logo_url"]
        if results[url][0]:
            local_url = RAW_BASE + targets[url].name
            if guide_id in by_id:
                by_id[guide_id]["logo_url"] = local_url
            else:
                by_id[guide_id] = {"guide_id": guide_id, "logo_url": local_url}
                existing.append(by_id[guide_id])
            replaced += 1
        else:
            unavailable.append(guide_id)
    with logos_csv.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["guide_id", "logo_url"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(existing)
    print(f"Pink M3U trial: {replaced} source logos replaced; {len(unavailable)} unavailable: {', '.join(unavailable)}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: host_m3u_pink_logos.py manifest.csv logos.csv logos/")
    main(*(Path(p) for p in sys.argv[1:]))
