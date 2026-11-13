#!/usr/bin/env python3
"""Fetch TVProfil schedules through a real browser session and inject them into XMLTV."""

import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ZONE = ZoneInfo("Europe/Zagreb")
PAGE_CANDIDATES = [
    "https://tvprofil.com/",
    "https://tvprofil.com/hr/",
    "https://tvprofil.com/box/",
    "https://tvprofil.com/hr/tvprogram/kanal/{slug}",
    "https://tvprofil.com/tvprogram/kanal/{slug}",
    "https://tvprofil.com/ba/tvprogram/kanal/{slug}",
]
JS_FETCH = r"""
async ({slug, datum}) => {
  if (typeof bazinga !== "function") {
    throw new Error("TVProfil bazinga() is not available");
  }

  const data = {
    datum,
    kanal: slug
  };

  bazinga(data);

  const bKey = Object.keys(data).find(k => /^b\d+$/.test(k));
  if (!bKey) throw new Error("TVProfil bKey not found");

  const lang = Tvprofil?.config?.lang || "";
  const callback = "tvprogram" + lang + bKey;

  const url =
    "/tvprogram/program/?" +
    "callback=" + encodeURIComponent(callback) +
    "&datum=" + encodeURIComponent(datum) +
    "&kanal=" + encodeURIComponent(slug) +
    "&" + bKey + "=" + encodeURIComponent(data[bKey]);

  const response = await fetch(url, {
    credentials: "include",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "Accept": "text/javascript, application/javascript, application/json, */*"
    }
  });

  const raw = await response.text();
  const match = raw.match(/^[^(]+\(([\s\S]*)\)\s*;?\s*$/);
  if (!match) throw new Error("TVProfil JSONP parse failed");

  const json = JSON.parse(match[1]);
  if (json.code !== 0) {
    throw new Error("TVProfil returned code " + json.code);
  }

  const html = json?.data?.program || "";
  const container = document.createElement("div");
  container.innerHTML = html;

  return [...container.querySelectorAll(".row[data-ts][data-len]")].map(row => {
    const ts = Number(row.dataset.ts);
    const len = Number(row.dataset.len);
    const link = row.querySelector("a");

    return {
      ts,
      len,
      title: (link?.textContent || "").replace(/\s+/g, " ").trim(),
      canonical_title: link?.getAttribute("title") || "",
      category: (row.querySelector("small")?.textContent || "").replace(/\s+/g, " ").trim(),
      live: !!row.querySelector(".label"),
      image: row.dataset.image || "",
      program_id: row.querySelector("[data-pid]")?.getAttribute("data-pid") || "",
      href: link?.getAttribute("href") || ""
    };
  });
}
"""

def iso_day(offset):
    return (date.today() + timedelta(days=offset)).isoformat()

def fmt_xmltv(ts):
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(ZONE).strftime("%Y%m%d%H%M%S %z")

def main(guide_path, config_path):
    channels = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not channels:
        raise SystemExit("TVProfil channel configuration is empty")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            locale="hr-HR",
            timezone_id="Europe/Zagreb",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['hr-HR', 'hr', 'en-US', 'en']});
            Object.defineProperty(navigator, 'platform', {get: () => 'Linux x86_64'});
        """)

        loaded = False
        last_error = None
        for template in PAGE_CANDIDATES:
            try:
                target = template.format(slug=channels[0]["slug"])
                response = page.goto(target, wait_until="load", timeout=60000)
                status = response.status if response else "no-response"
                try:
                    page.wait_for_function(
                        "typeof Tvprofil !== 'undefined' && (typeof bazinga === 'function' || typeof window.bazinga === 'function')",
                        timeout=20000,
                    )
                    loaded = True
                    print("TVProfil session:", page.url, "| status:", status, "| title:", page.title())
                    break
                except Exception as wait_exc:
                    body = page.locator("body").inner_text(timeout=5000)[:500].replace("\n", " | ")
                    print("TVProfil candidate failed:", target)
                    print("  final URL:", page.url, "| status:", status, "| title:", page.title())
                    print("  body:", body)
                    print("  Tvprofil:", page.evaluate("typeof Tvprofil"))
                    print("  bazinga:", page.evaluate("typeof bazinga"))
                    last_error = wait_exc
            except Exception as exc:
                print("TVProfil navigation failed:", template, "|", exc)
                last_error = exc

        if not loaded:
            browser.close()
            raise SystemExit(f"Could not establish TVProfil browser session: {last_error}")

        all_events = []
        errors = []

        # Probe a generous window around today. Empty days are ignored.
        # This avoids hard-coding TVProfil's currently observed 13-day range.
        for channel in channels:
            channel_events = []
            for offset in range(-14, 15):
                datum = iso_day(offset)
                try:
                    events = page.evaluate(JS_FETCH, {"slug": channel["slug"], "datum": datum})
                except Exception as exc:
                    errors.append(f'{channel["slug"]} {datum}: {exc}')
                    continue

                for event in events:
                    event["xmltv_id"] = channel["xmltv_id"]
                    event["slug"] = channel["slug"]
                    event["requested_date"] = datum
                    channel_events.append(event)

                time.sleep(0.08)

            if not channel_events:
                errors.append(f'{channel["slug"]}: no programmes found in probe window')
            print(f'{channel["xmltv_id"]}: {len(channel_events)} programmes')
            all_events.extend(channel_events)

        browser.close()

    if errors:
        print("TVProfil fetch warnings/errors:")
        for error in errors:
            print("  " + error)
        if any("no programmes found" in e for e in errors):
            raise SystemExit("At least one configured TVProfil channel returned no programmes")

    # TVProfil occasionally includes a timed row without a programme title.
    # Keep it out of XMLTV and report it explicitly instead of inventing a title.
    untitled = [e for e in all_events if not e["title"]]
    if untitled:
        print(f"TVProfil untitled rows skipped: {len(untitled)}")
        for e in untitled[:20]:
            print(f'  {e["slug"]} {e["requested_date"]} ts={e["ts"]} len={e["len"]}')
        all_events = [e for e in all_events if e["title"]]
    missing_programmes = {c["xmltv_id"] for c in channels} - {e["xmltv_id"] for e in all_events}
    if missing_programmes:
        raise SystemExit("TVProfil channels without titled programmes: " + ", ".join(sorted(missing_programmes)))

    # Validate before touching the XML tree.
    invalid = [
        e for e in all_events
        if not isinstance(e["ts"], (int, float))
        or not isinstance(e["len"], (int, float))
        or e["len"] <= 0
        or not e["title"]
    ]
    if invalid:
        raise SystemExit(f"Invalid TVProfil programme records: {len(invalid)}")

    seen = set()
    duplicates = []
    for e in all_events:
        key = (e["xmltv_id"], int(e["ts"]), int(e["len"]), e["program_id"], e["title"])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise SystemExit(f"TVProfil duplicate programmes detected: {len(duplicates)}")

    tree = ET.parse(guide_path)
    root = tree.getroot()
    configured_ids = {c["xmltv_id"] for c in channels}

    existing_ids = {c.get("id") for c in root.findall("channel")}
    missing_channels = configured_ids - existing_ids
    if missing_channels:
        raise SystemExit("Configured TVProfil XMLTV channels missing from guide: " + ", ".join(sorted(missing_channels)))

    # Remove old programmes for these six IDs only after all source validation passed.
    for programme in list(root.findall("programme")):
        if programme.get("channel") in configured_ids:
            root.remove(programme)

    by_channel = {c["xmltv_id"]: c for c in channels}
    for event in sorted(all_events, key=lambda e: (e["xmltv_id"], e["ts"])):
        start = int(event["ts"])
        stop = start + int(event["len"])
        node = ET.SubElement(root, "programme", {
            "channel": event["xmltv_id"],
            "start": fmt_xmltv(start),
            "stop": fmt_xmltv(stop),
        })

        ET.SubElement(node, "title", lang="hr").text = event["title"]

        if event["canonical_title"] and event["canonical_title"] != event["title"]:
            ET.SubElement(node, "sub-title", lang="hr").text = event["canonical_title"]

        if event["category"]:
            ET.SubElement(node, "category", lang="hr").text = event["category"]

        if event["live"]:
            ET.SubElement(node, "category", lang="hr").text = "Uživo"

        if event["image"]:
            ET.SubElement(node, "icon", {"src": event["image"]})

    ET.indent(tree, space="  ")
    tree.write(guide_path, encoding="utf-8", xml_declaration=True)

    print("========================================")
    print("TVProfil import completed")
    print(f"Channels:   {len(channels)}")
    print(f"Programmes: {len(all_events)}")
    print("Source:     TVProfil browser/JSONP")
    print("Timezone:   Europe/Zagreb")
    print("========================================")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: import_tvprofil.py guide.xml config/tvprofil_channels.json")
    main(sys.argv[1], sys.argv[2])
