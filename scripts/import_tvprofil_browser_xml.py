#!/usr/bin/env python3
"""Validate a locally exported TVProfil XMLTV file and merge only its channels."""
from __future__ import annotations

import argparse
import copy
import csv
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
    parser.add_argument("--aliases", type=Path, default=Path("config/playlist_aliases.csv"))
    args = parser.parse_args()
    if args.output.resolve() in {args.guide.resolve(), args.export.resolve()}:
        raise SystemExit("Output path must differ from both input paths")

    allowed = {c["xmltv_id"] for c in json.loads(args.config.read_text(encoding="utf-8"))}
    aliases = {}
    if args.aliases.exists():
        with args.aliases.open(newline="", encoding="utf-8-sig") as f:
            aliases = {r["playlist_tvg_id"].strip(): r["guide_id"].strip()
                       for r in csv.DictReader(f)}
    source = ET.parse(args.export).getroot()
    export_ids, count = validate(source, allowed | {a for a, target in aliases.items() if target in allowed})
    ids = {aliases.get(cid, cid) for cid in export_ids}
    if len(ids) != len(export_ids):
        raise ValueError("Multiple exported channels map to the same guide channel")
    tree = ET.parse(args.guide)
    root = tree.getroot()
    existing_channels = {n.get("id") for n in root.findall("channel")}
    first_programme = root.find("programme")
    insert_at = list(root).index(first_programme) if first_programme is not None else len(root)
    for node in source.findall("channel"):
        target = aliases.get(node.get("id"), node.get("id"))
        if target not in existing_channels:
            channel = copy.deepcopy(node)
            channel.set("id", target)
            root.insert(insert_at, channel)
            insert_at += 1
    affected_aliases = {a: target for a, target in aliases.items()
                        if target in ids and a in existing_channels}
    old = [node for node in root.findall("programme")
           if node.get("channel") in ids or node.get("channel") in affected_aliases]
    for node in old:
        root.remove(node)
    for node in source.findall("programme"):
        target = aliases.get(node.get("channel"), node.get("channel"))
        programme = copy.deepcopy(node)
        programme.set("channel", target)
        root.append(programme)
        for alias, alias_target in affected_aliases.items():
            if alias_target == target:
                duplicate = copy.deepcopy(programme)
                duplicate.set("channel", alias)
                root.append(duplicate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"Validated {count} source programmes across {len(ids)} channels")
    print(f"Replaced {len(old)} old source/alias programmes; refreshed {len(affected_aliases)} aliases -> {args.output}")


if __name__ == "__main__":
    main()
