#!/usr/bin/env bash
set -euo pipefail

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

rollback_section() {
  local name="$1"
  echo "::warning::$name failed; rolling back only this section"
  git reset --hard HEAD
  git clean -fd -e epg/
}

commit_stage() {
  local message="$1"
  shift
  git add "$@"
  if ! git diff --cached --quiet; then
    git commit -m "$message"
  fi
}

run_section() {
  local name="$1"
  local fn="$2"
  set +e
  (
    set -e
    "$fn"
  )
  local status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    rollback_section "$name"
  fi
}

echo "Cloning shared EPG grabber..."
git clone --depth 1 https://github.com/iptv-org/epg.git epg

python3 - <<'PY'
from pathlib import Path

maxtv = Path('epg/sites/mojmaxtv.hrvatskitelekom.hr/mojmaxtv.hrvatskitelekom.hr.config.js')
content = maxtv.read_text(encoding='utf-8')
marker = "module.exports = {\n  site: SITE_URL,"
replacement = "module.exports = {\n  site: SITE_URL,\n  days: 3,"
if replacement not in content:
    if content.count(marker) != 1:
        raise SystemExit('MAXtv config structure changed upstream')
    maxtv.write_text(content.replace(marker, replacement, 1), encoding='utf-8')

mts = Path('epg/sites/mts.rs/mts.rs.config.js')
content = mts.read_text(encoding='utf-8')
old = "const channelData = data.products.find(c => c.code === channel.site_id)"
new = "const channelData = data.products.find(c => c.code === decodeURIComponent(channel.site_id))"
if new not in content:
    if content.count(old) != 1:
        raise SystemExit('MTS parser pattern changed upstream')
    mts.write_text(content.replace(old, new, 1), encoding='utf-8')
PY

(
  cd epg
  npm ci
)
python3 -m pip install Pillow lxml

serbia_extra() {
  (
    cd epg
    npm run grab --- \
      --channels=../config/serbia-extra-mts.xml \
      --output=../serbia-extra-mts.xml \
      --maxConnections=5
  )

  python3 scripts/merge_xmltv.py guide.xml serbia-extra-mts.xml guide.serbia-extra.xml
  mv guide.serbia-extra.xml guide.xml

  python3 scripts/import_mts_pink_hahalol.py
  python3 scripts/merge_xmltv.py guide.xml pink-hahalol-mts.xml guide.serbia-extra-pink.xml
  mv guide.serbia-extra-pink.xml guide.xml

  python3 scripts/host_m3u_serbia_logos.py \
    config/serbia-extra-mts-logos.csv config/bih-source-logos.csv logos
  python3 scripts/add_channel_logos.py guide.xml config/bih-source-logos.csv

  python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

all_channels = [
    'insajdertv.rs', 'Balkan Trip', 'AgroTV.rs', '101TV.rs',
    'SOS Kanal Plus', 'pinkhaha.rs', 'lol.rs'
]
epg_required = ['insajdertv.rs', 'AgroTV.rs', 'pinkhaha.rs', 'lol.rs']
root = ET.parse('guide.xml').getroot()
counts = Counter(p.get('channel') for p in root.findall('programme'))
channels = {c.get('id'): c for c in root.findall('channel')}
failed = []

for cid in all_channels:
    if cid not in channels:
        failed.append(f'{cid}: missing channel')
        continue
    icon = channels[cid].find('icon')
    if icon is None or not icon.get('src'):
        failed.append(f'{cid}: no logo')
    print(cid, counts[cid], 'programmes')

for cid in epg_required:
    if counts[cid] == 0:
        failed.append(f'{cid}: 0 programmes')

if failed:
    raise SystemExit('; '.join(failed))
PY

  commit_stage "Stage Serbia extra EPG" guide.xml config/bih-source-logos.csv logos/
}

croatia_extra() {
  (
    cd epg
    npm run grab --- \
      --channels=../config/croatia-extra-channels.xml \
      --output=../croatia-extra.xml \
      --maxConnections=3
  )

  python3 scripts/merge_xmltv.py guide.xml croatia-extra.xml guide.croatia.xml
  mv guide.croatia.xml guide.xml

  python3 scripts/import_nova_cinema_raspored.py guide.xml
  python3 scripts/import_nova_family_tvprogramdanas.py guide.xml
  python3 scripts/import_nova_world_tvepg.py guide.xml logos
  python3 scripts/add_croatia_epg_aliases.py guide.xml config/croatia-playlist-aliases.csv
  python3 scripts/apply_m3u_croatia_playlist_logos.py \
    guide.xml config/m3u-croatia-playlist-logos.csv logos

  python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

root = ET.parse('guide.xml').getroot()
wanted = [
    'htv5', 'N1Croatia.hr', 'zdravatv.hr',
    'nova-plus-cinema', 'nova-plus-family', 'prvaworld.rs'
]
required = [
    'N1Croatia.hr', 'zdravatv.hr',
    'nova-plus-cinema', 'nova-plus-family', 'prvaworld.rs'
]
channels = {c.get('id') for c in root.findall('channel')}
counts = Counter(p.get('channel') for p in root.findall('programme'))

for cid in wanted:
    if cid not in channels:
        raise SystemExit(f'Missing Croatia channel: {cid}')
    print(cid, counts[cid], 'programmes')

for cid in required:
    if counts[cid] == 0:
        raise SystemExit(f'No programmes for required Croatia channel: {cid}')

if counts['htv5'] == 0:
    print('WARNING: HRT INT has no programme data; keeping channel/logo')
PY

  commit_stage "Stage Croatia extra EPG" guide.xml config/bih-source-logos.csv logos/
}

hype_extra() {
  (
    cd epg
    npm run grab --- \
      --channels=../config/hype-mts.xml \
      --output=../hype-mts.xml \
      --maxConnections=2
  )

  python3 scripts/merge_xmltv.py guide.xml hype-mts.xml guide.hype.xml
  mv guide.hype.xml guide.xml

  python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

path = 'guide.xml'
tree = ET.parse(path)
root = tree.getroot()
logos = {
    'HypeTV.rs': 'http://telekomsrbije.com:2095/images/hype.png',
    'hype-tv': 'http://telekomsrbije.com:2095/images/hype2.png',
}
names = {'HypeTV.rs': 'Hype TV', 'hype-tv': 'Hype 2'}
channels = {c.get('id'): c for c in root.findall('channel')}
counts = Counter(p.get('channel') for p in root.findall('programme'))

for cid, logo in logos.items():
    channel = channels.get(cid)
    if channel is None:
        channel = ET.Element('channel', {'id': cid})
        ET.SubElement(channel, 'display-name').text = names[cid]
        root.insert(len(root.findall('channel')), channel)
    icon = channel.find('icon')
    if icon is None:
        icon = ET.SubElement(channel, 'icon')
    icon.set('src', logo)
    if counts[cid] == 0:
        raise SystemExit(f'No MTS programmes for {cid}')
    print(cid, counts[cid], 'programmes')

tree.write(path, encoding='utf-8', xml_declaration=True)
PY

  commit_stage "Stage Hype MTS EPG" guide.xml
}

informer_extra() {
  (
    cd epg
    npm run grab --- \
      --channels=../config/informer-mts.xml \
      --output=../informer-mts.xml \
      --maxConnections=2
  )

  python3 scripts/merge_xmltv.py guide.xml informer-mts.xml guide.informer.xml
  mv guide.informer.xml guide.xml

  python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

path = 'guide.xml'
tree = ET.parse(path)
root = tree.getroot()
channel = next(
    (c for c in root.findall('channel') if c.get('id') == 'informertv.rs'),
    None
)
if channel is None:
    raise SystemExit('Missing informertv.rs channel')

counts = Counter(p.get('channel') for p in root.findall('programme'))
if counts['informertv.rs'] == 0:
    raise SystemExit('No MTS programmes for informertv.rs')

for icon in list(channel.findall('icon')):
    channel.remove(icon)
ET.SubElement(channel, 'icon', {
    'src': 'https://raw.githubusercontent.com/CryptoArch65/my-epg/main/logos/m3u-serbia-c69abbf615166141.png'
})
tree.write(path, encoding='utf-8', xml_declaration=True)
print('informertv.rs', counts['informertv.rs'], 'programmes')
PY

  commit_stage "Stage Informer MTS EPG" guide.xml
}

croatia_logos() {
  python3 scripts/host_m3u_croatia_logos.py \
    config/m3u-croatia-logo-trial.csv config/bih-source-logos.csv logos
  python3 scripts/apply_m3u_croatia_playlist_logos.py \
    guide.xml config/m3u-croatia-playlist-logos.csv logos

  commit_stage "Stage Croatia logos" \
    guide.xml config/bih-source-logos.csv logos/
}

bih_local() {
  python3 scripts/import_bih_local_channels.py guide.xml logos

  python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

root = ET.parse('guide.xml').getroot()
channels = {c.get('id'): c for c in root.findall('channel')}
counts = Counter(p.get('channel') for p in root.findall('programme'))

for cid in ('TVZivinice.ba', 'RTVCazin.ba', 'TVPodrinje.ba'):
    if cid not in channels:
        raise SystemExit(f'Missing BIH local channel: {cid}')
    icon = channels[cid].find('icon')
    if icon is None or not icon.get('src'):
        raise SystemExit(f'Missing logo for BIH local channel: {cid}')

if counts['TVPodrinje.ba'] < 40:
    raise SystemExit(f'TV Podrinje EPG too short: {counts["TVPodrinje.ba"]}')
print('TVPodrinje.ba', counts['TVPodrinje.ba'], 'programmes')
PY

  commit_stage "Stage BIH local EPG" guide.xml logos/
}

run_section "Serbia extra EPG" serbia_extra
run_section "Croatia extra EPG" croatia_extra
run_section "Hype MTS EPG" hype_extra
run_section "Informer MTS EPG" informer_extra
run_section "Croatia logos" croatia_logos
run_section "BIH local EPG" bih_local

python3 - <<'PY'
import xml.etree.ElementTree as ET
from collections import Counter

root = ET.parse('guide.xml').getroot()
if root.tag != 'tv':
    raise SystemExit('Invalid XMLTV root')

channels = [c.get('id') for c in root.findall('channel')]
if len(channels) != len(set(channels)):
    raise SystemExit('Duplicate XMLTV channel IDs after extras')

counts = Counter(p.get('channel') for p in root.findall('programme'))
print('Final extras guide:', len(channels), 'channels,',
      sum(counts.values()), 'programmes')
PY

if git diff origin/main..HEAD --quiet; then
  echo "No extra EPG changes to publish"
  exit 0
fi

git clean -fd -e epg/
git fetch origin main
git rebase origin/main
git push origin HEAD:main
