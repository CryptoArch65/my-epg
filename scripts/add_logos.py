import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET


GUIDE_FILE = "guide.xml"

CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
LOGOS_URL = "https://iptv-org.github.io/api/logos.json"


# ---------------------------------------------------------
# SOURCE -> preferred country
# ---------------------------------------------------------

SOURCE_COUNTRY = {
    "telemach.ba": "ba",
    "mtel.ba": "ba",
    "mts.rs": "rs",
    "hrvatskitelekom.hr": "hr",
    "arenasport.hr": "hr",
    "arenasport": "rs",
}


# ---------------------------------------------------------
# Explicit aliases
#
# These are used when the IPTV provider name is different
# from the official iptv-org channel name.
# ---------------------------------------------------------

ALIASES = {
    "bht 1": "BHT1.ba",
    "bht 1 hd": "BHT1.ba",
    "bht1": "BHT1.ba",
    "bht1 hd": "BHT1.ba",

    "ftv": "Federalnatelevizija.ba",
    "ftv hd": "Federalnatelevizija.ba",
    "federalna tv": "Federalnatelevizija.ba",
    "federalna televizija": "Federalnatelevizija.ba",
    "federalna tv hd": "Federalnatelevizija.ba",

    "hrt 1": "HRT1.hr",
    "hrt 1 hd": "HRT1.hr",
    "hrt1": "HRT1.hr",
    "hrt1 hd": "HRT1.hr",

    "arena sport 1 bih": "ArenaSport1.ba",
    "arena sport 1 bosna i hercegovina": "ArenaSport1.ba",

    "arena sport 1 hr": "ArenaSport1.hr",
    "arena sport 1 hrvatska": "ArenaSport1.hr",

    "arena sport 1 premium": "ArenaSport1Premium.rs",
    "arena sport 1 premium srbija": "ArenaSport1Premium.rs",

    "cinestar tv 1 serbia": "CineStarTV1.rs",
    "cinestar tv 1 slovenia": "CineStarTV1.si",
}


# ---------------------------------------------------------
# Text normalization
# ---------------------------------------------------------

def normalize(text):
    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )

    text = text.lower()

    text = text.replace("&", " and ")

    # Remove country / technical suffixes
    text = re.sub(
        r"\((sr\/bih|bih|me|hr|rs|srb|cg|slovenia|serbia|croatia)\)",
        " ",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\b(uhd|fhd|hd|sd)\b",
        " ",
        text
    )

    # Replace punctuation with spaces
    text = re.sub(r"[^a-z0-9]+", " ", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text


# ---------------------------------------------------------
# Download JSON
# ---------------------------------------------------------

def load_json(url):
    print(f"Downloading {url}")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CryptoArch65/my-epg"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        return json.load(response)


# ---------------------------------------------------------
# Build channel database
# ---------------------------------------------------------

def build_channel_map(channels):
    channel_map = {}

    for channel in channels:

        channel_id = channel.get("id")

        if not channel_id:
            continue

        names = []

        name = channel.get("name")

        if name:
            names.append(name)

        names.extend(
            channel.get("alt_names", [])
        )

        for value in names:

            key = normalize(value)

            if not key:
                continue

            channel_map.setdefault(
                key,
                []
            ).append(channel_id)

    return channel_map


# ---------------------------------------------------------
# Build logo database
# ---------------------------------------------------------

def build_logo_map(logos):

    logo_map = {}

    for logo in logos:

        if not logo.get("in_use"):
            continue

        channel_id = logo.get("channel")
        url = logo.get("url")

        if not channel_id or not url:
            continue

        score = 0

        # Prefer logos without a feed because these are
        # usually the general channel logo.
        if not logo.get("feed"):
            score += 50

        # Prefer SVG, then PNG.
        fmt = (
            logo.get("format") or ""
        ).upper()

        if fmt == "SVG":
            score += 100

        elif fmt == "PNG":
            score += 90

        elif fmt == "WEBP":
            score += 80

        # Prefer larger images.
        width = logo.get("width") or 0

        score += min(
            width,
            2000
        ) / 1000

        existing = logo_map.get(channel_id)

        if (
            existing is None
            or score > existing["score"]
        ):
            logo_map[channel_id] = {
                "url": url,
                "score": score
            }

    return logo_map


# ---------------------------------------------------------
# Find exact / alias match
# ---------------------------------------------------------

def find_channel_id(
    display_name,
    source,
    channel_map
):

    original = display_name.strip()

    normalized = normalize(
        original
    )

    # -----------------------------------------------------
    # 1. Explicit alias
    # -----------------------------------------------------

    alias_id = ALIASES.get(
        normalized
    )

    if alias_id:
        return alias_id, "ALIAS"

    # -----------------------------------------------------
    # 2. Source-aware special cases
    # -----------------------------------------------------

    if normalized == "arena sport 1":

        country = SOURCE_COUNTRY.get(
            source
        )

        if country == "ba":
            return "ArenaSport1.ba", "SOURCE"

        if country == "hr":
            return "ArenaSport1.hr", "SOURCE"

        if country == "rs":
            # Prefer normal Serbian Arena Sport 1
            # if present in channels.json.
            candidates = channel_map.get(
                "arena sport 1",
                []
            )

            for cid in candidates:

                if cid.endswith(".rs"):
                    return cid, "SOURCE"

    # -----------------------------------------------------
    # 3. Exact name match
    # -----------------------------------------------------

    candidates = channel_map.get(
        normalized,
        []
    )

    if not candidates:
        return None, None

    # If only one candidate exists,
    # use it immediately.
    if len(candidates) == 1:
        return candidates[0], "EXACT"

    # -----------------------------------------------------
    # 4. Prefer country matching source
    # -----------------------------------------------------

    preferred_country = SOURCE_COUNTRY.get(
        source
    )

    if preferred_country:

        for cid in candidates:

            if cid.lower().endswith(
                "." + preferred_country
            ):
                return cid, "COUNTRY"

    # -----------------------------------------------------
    # 5. Otherwise return first candidate
    # -----------------------------------------------------

    return candidates[0], "EXACT"


# ---------------------------------------------------------
# Special fallback for CineStar
# ---------------------------------------------------------

def cinestar_fallback(
    display_name,
    source,
    channel_map
):

    normalized = normalize(
        display_name
    )

    if normalized != "cinestar tv 1":
        return None, None

    # For a BIH CineStar channel, iptv-org currently
    # does not provide a dedicated CineStarTV1.ba ID.
    #
    # Use Croatian version for Croatian/BiH EPG sources,
    # otherwise Serbian version.
    if source in (
        "telemach.ba",
        "mtel.ba",
    ):
        return "CineStarTV1.hr", "CINESTAR-FALLBACK"

    if source == "mts.rs":
        return "CineStarTV1.rs", "CINESTAR-FALLBACK"

    return None, None


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    print()
    print("==============================================")
    print(" IPTV-ORG LOGO PROCESSOR")
    print("==============================================")
    print()

    # -----------------------------------------------------
    # Download current iptv-org data
    # -----------------------------------------------------

    channels = load_json(
        CHANNELS_URL
    )

    logos = load_json(
        LOGOS_URL
    )

    print(
        f"Channels loaded: {len(channels)}"
    )

    print(
        f"Logo records loaded: {len(logos)}"
    )

    # -----------------------------------------------------
    # Build lookup tables
    # -----------------------------------------------------

    channel_map = build_channel_map(
        channels
    )

    logo_map = build_logo_map(
        logos
    )

    print(
        f"Channel names indexed: {len(channel_map)}"
    )

    print(
        f"Active logos indexed: {len(logo_map)}"
    )

    print()

    # -----------------------------------------------------
    # Load guide.xml
    # -----------------------------------------------------

    tree = ET.parse(
        GUIDE_FILE
    )

    root = tree.getroot()

    found = 0
    missing = 0
    replaced = 0

    # -----------------------------------------------------
    # Process channels
    # -----------------------------------------------------

    for channel in root.findall(
        "channel"
    ):

        display_name = channel.findtext(
            "display-name",
            default=""
        ).strip()

        channel_id = channel.get(
            "id",
            ""
        )

        if not display_name:
            continue

        # -------------------------------------------------
        # Determine source from our normalized EPG ID
        # -------------------------------------------------

        source = None

        for suffix in SOURCE_COUNTRY:

            if channel_id.endswith(
                "." + suffix
            ):
                source = suffix
                break

        # -------------------------------------------------
        # Remove old/source-specific icon
        # -------------------------------------------------

        old_icon = channel.find(
            "icon"
        )

        if old_icon is not None:
            channel.remove(
                old_icon
            )

            replaced += 1

        # -------------------------------------------------
        # Find iptv-org channel
        # -------------------------------------------------

        iptv_id, match_type = find_channel_id(
            display_name,
            source,
            channel_map
        )

        # -------------------------------------------------
        # CineStar special fallback
        # -------------------------------------------------

        if not iptv_id:

            iptv_id, match_type = cinestar_fallback(
                display_name,
                source,
                channel_map
            )

        # -------------------------------------------------
        # No channel found
        # -------------------------------------------------

        if not iptv_id:

            missing += 1

            print(
                f"NO MATCH | {display_name} | "
                f"source={source}"
            )

            continue

        # -------------------------------------------------
        # Find logo
        # -------------------------------------------------

        logo = logo_map.get(
            iptv_id
        )

        if not logo:

            missing += 1

            print(
                f"NO LOGO  | {display_name} | "
                f"iptv-org={iptv_id}"
            )

            continue

        # -------------------------------------------------
        # Add logo
        # -------------------------------------------------

        ET.SubElement(
            channel,
            "icon",
            {
                "src": logo["url"]
            }
        )

        found += 1

        print(
            f"LOGO     | {display_name} | "
            f"{iptv_id} | {match_type}"
        )

    # -----------------------------------------------------
    # Save
    # -----------------------------------------------------

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        GUIDE_FILE,
        encoding="utf-8",
        xml_declaration=True
    )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()
    print("==============================================")
    print(" LOGO PROCESSING COMPLETED")
    print("==============================================")
    print(
        f"Logos added:       {found}"
    )
    print(
        f"Without logo:      {missing}"
    )
    print(
        f"Old icons removed: {replaced}"
    )
    print("==============================================")


if __name__ == "__main__":
    main()
