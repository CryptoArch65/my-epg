#!/usr/bin/env python3
"""Remove duplicate XMLTV alias channels for selected Serbian regionals.

Keep only the canonical IDs used by the playlist/TiviMate mapping:
- TVAS.rs
- PesterTV.rs
- RTVKraljevo.rs

The aliases are useful during discovery/migration but make TiviMate's manual
EPG assignment list show several identical choices. Playlist-side mapping now
uses the canonical IDs, so these XMLTV alias channels are no longer needed.
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CANONICAL_ALIASES = {
    "TVAS.rs": ("TV AS", "tv_as", "as_tv"),
    "PesterTV.rs": ("Pester TV", "Pešter TV", "pester_tv", "tv_pester"),
    "RTVKraljevo.rs": ("TV Kraljevo", "RTV Kraljevo", "tv_kraljevo", "rtv_kraljevo"),
}


def main(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    channel_ids = {channel.get("id") for channel in root.findall("channel")}

    missing = [canonical for canonical in CANONICAL_ALIASES if canonical not in channel_ids]
    if missing:
        raise SystemExit(
            "Refusing alias cleanup because canonical channel(s) are missing: "
            + ", ".join(missing)
        )

    aliases = {
        alias
        for canonical, values in CANONICAL_ALIASES.items()
        for alias in values
        if alias != canonical
    }

    removed_channels = []
    for channel in list(root.findall("channel")):
        channel_id = channel.get("id")
        if channel_id in aliases:
            root.remove(channel)
            removed_channels.append(channel_id)

    removed_programmes = 0
    for programme in list(root.findall("programme")):
        if programme.get("channel") in aliases:
            root.remove(programme)
            removed_programmes += 1

    tree.write(path, encoding="utf-8", xml_declaration=True)

    print(
        "Regional alias cleanup: "
        f"removed {len(removed_channels)} channel(s), "
        f"{removed_programmes} programme(s)"
    )
    if removed_channels:
        print("Removed aliases: " + ", ".join(sorted(removed_channels)))
    for canonical in CANONICAL_ALIASES:
        print(f"Kept canonical: {canonical}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: remove_duplicate_regional_aliases.py guide.xml")
    main(Path(sys.argv[1]))
