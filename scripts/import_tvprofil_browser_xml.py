#!/usr/bin/env python3
"""Validate a locally exported TVProfil XMLTV file and merge only its channels."""
from __future__ import annotations

import argparse
import copy
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def validate(source: ET.Element, allowed_ids: set[str]) -> tuple[set[str], int]:
    channel_nodes = source.findall("channel")
    ids = [node.get("id") for node in channel_nodes]
    if not ids or len(set(ids)) != len(ids) or not set(ids) <= allowed_ids:
        raise ValueError("XML contains missing, duplicate, or unapproved channel IDs")

    per_channel = defaultdict(list)
    seen = set()
    for node in source.findall("programme"):
        cid = node.get("channel")
        if cid not in ids or not (node.findtext("title") or "").strip():
            raise ValueError("Programme has an unknown channel or an empty title")
        try:
            start = datetime.strptime(node.attrib["start"], "%Y%m%d%H%M%S %z")
            stop = datetime.strptime(node.attrib["stop"], "%Y%m%d%H%M%S %z")
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid programme time for {cid}") from exc
        if start >= stop:
            raise ValueError(f"Nonpositive programme duration for {cid}")
        key = (cid, start, stop, node.findtext("title"))
        if key in seen:
            raise ValueError(f"Duplicate programme for {cid} at {start}")
        seen.add(key)
        per_channel[cid].append((start, stop))

    if set(per_channel) != set(ids):
        raise ValueError("Every exported channel must have at least one programme")
    for cid, intervals in per_channel.items():
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                raise ValueError(f"Overlapping programmes for {cid}")
    return set(ids), len(seen)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("guide", type=Path, help="Existing XMLTV guide")
    parser.add_argument("export", type=Path, help="Browser-exported XMLTV file")
    parser.add_argument("output", type=Path, help="New guide path; input remains unchanged")
    parser.add_argument("--config", type=Path, default=Path("config/tvprofil_channels.json"))
    args = parser.parse_args()
    if args.output.resolve() in {args.guide.resolve(), args.export.resolve()}:
        raise SystemExit("Output path must differ from both input paths")

    allowed = {c["xmltv_id"] for c in json.loads(args.config.read_text(encoding="utf-8"))}
    source = ET.parse(args.export).getroot()
    ids, count = validate(source, allowed)
    tree = ET.parse(args.guide)
    root = tree.getroot()
    existing_channels = {n.get("id") for n in root.findall("channel")}
    first_programme = root.find("programme")
    insert_at = list(root).index(first_programme) if first_programme is not None else len(root)
    for node in source.findall("channel"):
        if node.get("id") not in existing_channels:
            root.insert(insert_at, copy.deepcopy(node))
            insert_at += 1
    old = [node for node in root.findall("programme") if node.get("channel") in ids]
    for node in old:
        root.remove(node)
    for node in source.findall("programme"):
        root.append(copy.deepcopy(node))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"Validated {count} programmes across {len(ids)} channels")
    print(f"Replaced {len(old)} old programmes -> {args.output}")


if __name__ == "__main__":
    main()
