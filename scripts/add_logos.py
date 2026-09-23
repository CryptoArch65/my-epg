import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET


GUIDE_FILE = "guide.xml"

CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
LOGOS_URL = "https://iptv-org.github.io/api/logos.json"


# =========================================================
# SOURCE -> COUNTRY
# =========================================================

SOURCE_COUNTRY = {
    "telemach.ba": "ba",
    "mtel.ba": "ba",
    "mts.rs": "rs",
    "hrvatskitelekom.hr": "hr",
    "arenasport.hr": "hr",
    "arenasport": "rs",
}


# =========================================================
# EXPLICIT ALIASES
#
# IMPORTANT:
# These override generic name matching.
# =========================================================

ALIASES = {

    # ---------------------------------------------
    # Bosnia and Herzegovina
    # ---------------------------------------------

    "bht 1": "BHT1.ba",
    "bht 1 hd": "BHT1.ba",
    "bht1": "BHT1.ba",
    "bht1 hd": "BHT1.ba",

    "ftv": "Federalnatelevizija.ba",
    "ftv hd": "Federalnatelevizija.ba",
    "federalna tv": "Federalnatelevizija.ba",
    "federalna tv hd": "Federalnatelevizija.ba",
    "federalna televizija": "Federalnatelevizija.ba",

    "n1 hd bh bih": "N1.ba",
    "n1 bih": "N1.ba",
    "n1 info bih": "N1.ba",
    "n1": "N1.ba",

    # ---------------------------------------------
    # Croatian
    # ---------------------------------------------

    "hrt 1": "HRT1.hr",
    "hrt 1 hd": "HRT1.hr",
    "hrt1": "HRT1.hr",
    "hrt1 hd": "HRT1.hr",

    # ---------------------------------------------
    # Arena Sport
    # ---------------------------------------------

    "arena sport 1 bih":
        "ArenaSport1.ba",

    "arena sport 1 bosna i hercegovina":
        "ArenaSport1.ba",

    "arena sport 1 hr":
        "ArenaSport1.hr",

    "arena sport 1 hrvatska":
        "ArenaSport1.hr",

    # ---------------------------------------------
    # CineStar
    # ---------------------------------------------

    "cinestar tv 1 serbia":
        "CineStarTV1.rs",

    "cinestar tv 1 slovenia":
        "CineStarTV1.si",
}


# =========================================================
# MANUAL CHANNEL MAP
#
# These are intentionally explicit because these names
# are ambiguous internationally.
#
# If an ID does not exist in the current iptv-org data,
# the script will NOT use a random alternative.
# =========================================================

MANUAL_MAP = {

    # ---------------------------------------------
    # Bosnia
    # ---------------------------------------------

    "rtrs":
        "RTRS.ba",

    "rtrs hd":
        "RTRS.ba",

    "face hd":
        "FaceTV.ba",

    "face tv":
        "FaceTV.ba",

    "sk 2 hd sr bih":
        "SportKlub2.ba",

    "sk 3 hd sr bih":
        "SportKlub3.ba",

    "sk 4 hd sr bih":
        "SportKlub4.ba",

    "sk golf hd sr":
        "SportKlubGolf.ba",

    "tlc hd bih":
        "TLC.ba",

    "alfa sarajevo":
        "AlfaTV.ba",
}


# =========================================================
# NORMALIZATION
# =========================================================

def normalize(text):

    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKD",
        text
    )

    text = "".join(
        c for c in text
        if not unicodedata.combining(c)
    )

    text = text.lower()

    text = text.replace(
        "&",
        " and "
    )

    # Country / regional markers
    text = re.sub(
        r"\((sr\/bih|bih|me|hr|rs|srb|cg|"
        r"slovenia|serbia|croatia)\)",
        " ",
        text,
        flags=re.IGNORECASE
    )

    # HD/SD/UHD markers
    text = re.sub(
        r"\b(uhd|fhd|hd|sd)\b",
        " ",
        text
    )

    # Everything else -> spaces
    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return text


# =========================================================
# DOWNLOAD JSON
# =========================================================

def load_json(url):

    print(
        f"Downloading {url}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent":
                "CryptoArch65/my-epg"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        return json.load(response)


# =========================================================
# CHANNEL DATABASE
# =========================================================

def build_channel_database(channels):

    database = {}

    for channel in channels:

        channel_id = channel.get(
            "id"
        )

        if not channel_id:
            continue

        names = []

        name = channel.get(
            "name"
        )

        if name:
            names.append(name)

        names.extend(
            channel.get(
                "alt_names",
                []
            )
        )

        country = (
            channel.get("country")
            or ""
        ).lower()

        for value in names:

            key = normalize(
                value
            )

            if not key:
                continue

            database.setdefault(
                key,
                []
            ).append(
                {
                    "id":
                        channel_id,

                    "country":
                        country,

                    "name":
                        name or "",

                    "alt_names":
                        channel.get(
                            "alt_names",
                            []
                        )
                }
            )

    return database


# =========================================================
# LOGO DATABASE
# =========================================================

def build_logo_database(logos):

    database = {}

    for logo in logos:

        if not logo.get(
            "in_use"
        ):
            continue

        channel_id = logo.get(
            "channel"
        )

        url = logo.get(
            "url"
        )

        if not channel_id or not url:
            continue

        score = 0

        # General channel logo
        if not logo.get(
            "feed"
        ):
            score += 50

        fmt = (
            logo.get("format")
            or ""
        ).upper()

        if fmt == "SVG":
            score += 100

        elif fmt == "PNG":
            score += 90

        elif fmt == "WEBP":
            score += 80

        elif fmt == "JPG":
            score += 70

        width = (
            logo.get("width")
            or 0
        )

        score += min(
            width,
            2000
        ) / 1000

        current = database.get(
            channel_id
        )

        if (
            current is None
            or score > current["score"]
        ):

            database[channel_id] = {
                "url": url,
                "score": score
            }

    return database


# =========================================================
# SOURCE FROM NORMALIZED GUIDE ID
# =========================================================

def get_source(channel_id):

    for suffix in SOURCE_COUNTRY:

        if channel_id.endswith(
            "." + suffix
        ):
            return suffix

    return None


# =========================================================
# SAFE COUNTRY MATCH
# =========================================================

def country_match(
    candidates,
    country
):

    if not country:
        return []

    return [
        item
        for item in candidates
        if item["country"] == country
    ]


# =========================================================
# FIND CHANNEL
# =========================================================

def find_channel(
    display_name,
    source,
    database
):

    normalized = normalize(
        display_name
    )

    # -----------------------------------------------------
    # 1. Explicit manual map
    # -----------------------------------------------------

    manual_id = MANUAL_MAP.get(
        normalized
    )

    if manual_id:
        return (
            manual_id,
            "MANUAL"
        )

    # -----------------------------------------------------
    # 2. Explicit aliases
    # -----------------------------------------------------

    alias_id = ALIASES.get(
        normalized
    )

    if alias_id:
        return (
            alias_id,
            "ALIAS"
        )

    # -----------------------------------------------------
    # 3. Exact name candidates
    # -----------------------------------------------------

    candidates = database.get(
        normalized,
        []
    )

    if not candidates:
        return (
            None,
            None
        )

    source_country = (
        SOURCE_COUNTRY.get(
            source
        )
        if source
        else None
    )

    # -----------------------------------------------------
    # 4. COUNTRY MUST WIN
    #
    # This prevents:
    #
    # TLC -> TLC.fr / TLC.in / TLC.nl
    #
    # when source is Bosnia.
    # -----------------------------------------------------

    country_candidates = country_match(
        candidates,
        source_country
    )

    if len(country_candidates) == 1:

        return (
            country_candidates[0]["id"],
            "COUNTRY"
        )

    if len(country_candidates) > 1:

        # Multiple channels in same country.
        # Do NOT guess.
        return (
            None,
            None
        )

    # -----------------------------------------------------
    # 5. If source country does not exist,
    # DO NOT use a random international channel.
    # -----------------------------------------------------

    return (
        None,
        None
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print(
        "=============================================="
    )

    print(
        " IPTV-ORG SAFE LOGO PROCESSOR"
    )

    print(
        "=============================================="
    )

    print()

    channels = load_json(
        CHANNELS_URL
    )

    logos = load_json(
        LOGOS_URL
    )

    print(
        f"Channels loaded: "
        f"{len(channels)}"
    )

    print(
        f"Logo records loaded: "
        f"{len(logos)}"
    )

    channel_database = (
        build_channel_database(
            channels
        )
    )

    logo_database = (
        build_logo_database(
            logos
        )
    )

    print(
        f"Channel names indexed: "
        f"{len(channel_database)}"
    )

    print(
        f"Active logos indexed: "
        f"{len(logo_database)}"
    )

    print()

    tree = ET.parse(
        GUIDE_FILE
    )

    root = tree.getroot()

    found = 0
    missing = 0
    removed = 0

    for channel in root.findall(
        "channel"
    ):

        display_name = channel.findtext(
            "display-name",
            default=""
        ).strip()

        guide_id = channel.get(
            "id",
            ""
        )

        if not display_name:
            continue

        source = get_source(
            guide_id
        )

        # -------------------------------------------------
        # REMOVE OLD LOGO
        # -------------------------------------------------

        old_icon = channel.find(
            "icon"
        )

        if old_icon is not None:

            channel.remove(
                old_icon
            )

            removed += 1

        # -------------------------------------------------
        # FIND IPTV-ORG CHANNEL
        # -------------------------------------------------

        iptv_id, match_type = find_channel(
            display_name,
            source,
            channel_database
        )

        # -------------------------------------------------
        # NO SAFE MATCH
        # -------------------------------------------------

        if not iptv_id:

            missing += 1

            print(
                f"NO SAFE MATCH | "
                f"{display_name} | "
                f"source={source}"
            )

            continue

        # -------------------------------------------------
        # FIND LOGO
        # -------------------------------------------------

        logo = logo_database.get(
            iptv_id
        )

        if not logo:

            missing += 1

            print(
                f"NO LOGO | "
                f"{display_name} | "
                f"iptv-org={iptv_id}"
            )

            continue

        # -------------------------------------------------
        # ADD LOGO
        # -------------------------------------------------

        ET.SubElement(
            channel,
            "icon",
            {
                "src":
                    logo["url"]
            }
        )

        found += 1

        print(
            f"LOGO | "
            f"{display_name} | "
            f"{iptv_id} | "
            f"{match_type}"
        )

    # -----------------------------------------------------
    # SAVE
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
    # SUMMARY
    # -----------------------------------------------------

    print()

    print(
        "=============================================="
    )

    print(
        " SAFE LOGO PROCESSING COMPLETED"
    )

    print(
        f"Logos added:       {found}"
    )

    print(
        f"No safe match:     {missing}"
    )

    print(
        f"Old icons removed: {removed}"
    )

    print(
        "=============================================="
    )


if __name__ == "__main__":
    main()
