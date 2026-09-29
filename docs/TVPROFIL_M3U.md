# M3U → TVProfil EPG

Ovaj dodatak omogućava da se lista kanala uzme iz M3U-a, da se naziv kanala ručno ispravi kada provider koristi pogrešan naziv, da se kanal spoji sa TVProfil kanalom i da se TVProfil raspored ubaci u XMLTV.

## Sigurnost

`tvprofil_m3u.py` čita stream URL-ove samo koliko je potrebno da pročita playlistu, ali ih **ne zapisuje** u CSV. U repozitorij se spremaju samo metadata kanala: naziv, grupa, tvg-id, tvg-name i logo.

Ako originalni M3U URL sadrži username/password/token, nemoj ga commitati u ovaj javni repo. Koristi lokalni fajl ili GitHub Actions secret.

## 1. Izvuci kanale iz M3U-a

```bash
python3 scripts/tvprofil_m3u.py /putanja/do/lista.m3u
```

ili:

```bash
python3 scripts/tvprofil_m3u.py "https://provider.example/list.m3u"
```

Rezultat je:

`config/tvprofil_playlist_channels.csv`

Kolona `corrected_name` je naziv koji smiješ ručno mijenjati. Kada ponovno importuješ M3U, postojeće ručne korekcije i potvrđeni TvProfil podaci ostaju sačuvani za isti `provider_name`.

## 2. Trajne ručne korekcije

Za korekcije koje želiš držati odvojeno od generisanog CSV-a koristi:

`config/tvprofil_name_overrides.csv`

Format:

```csv
provider_name,corrected_name,tvprofil_name,tvprofil_slug,enabled,note
|BIH| FTV HD,Federalna TV,,,yes,provider koristi pogrešan naziv
```

Ako znaš tačan TvProfil slug, možeš ga direktno upisati. Tada status postaje `manual` i automatski matcher se preskače za taj kanal.

`enabled=no` isključuje kanal iz TvProfil EPG-a.

## 3. Match prema TvProfilu

**Trenutno ograničenje (29. 9. 2026):** TvProfil vraća Cloudflare provjeru
GitHub Actions runneru. Zaseban test sa poznatim `tv-arena-sport-1-hr` slugom
je također vratio HTTP 403 i poruku "Blocked. Your browser is outdated" za
sve adrese koje postojeći importer pokušava. Zbog toga trenutno ni katalog ni
raspored sa TvProfila ne rade na tom runneru. Ovaj workflow je samo za ručni
pokušaj i neće promijeniti `guide.xml`.
Nemoj koristiti automatske rezultate bez pregleda, niti uključivati runtime
konfiguraciju u produkciju dok pristup katalogu i rasporedu nije potvrđen.

### Test iz vlastite TvProfil browser sesije

U razgovoru je potvrđeno da TvProfilov JSONP poziv radi u otvorenoj browser
sesiji. `scripts/tvprofil_browser_export.js` može se kopirati u konzolu na
TvProfil stranici. Po početnim postavkama preuzima raspored za šest Arena
kanala od sedam dana prije do pet dana poslije današnjeg datuma i sprema
`tvprofil-browser-test-YYYY-MM-DD.xml` lokalno. Skripta ne piše u GitHub.

Za drugi potvrđeni kanal prije pokretanja postavi:

```javascript
window.TVPROFIL_EXPORT_CHANNELS = [
  {xmltv_id: "moj.id", slug: "potvrdeni-tvprofil-slug", display_name: "Naziv kanala"}
];
```

Ovaj test zahtijeva otvorenu TvProfil sesiju i nije zamjena za automatski
GitHub workflow. XML prvo treba pregledati i validirati prije uvoza u vodič.

Nakon pregleda može se napraviti lokalna kopija vodiča s tim rasporedom:

```bash
python3 scripts/import_tvprofil_browser_xml.py guide.xml \
  /putanja/do/tvprofil-browser-test-YYYY-MM-DD.xml guide.review.xml
```

Importer prihvata samo ID-ove iz `config/tvprofil_channels.json`, provjerava
naslove, vrijeme, duplikate i preklapanja, pa mijenja samo programe tih kanala
u novom fajlu. Ne mijenja ulazni `guide.xml` i ništa ne objavljuje.

```bash
python3 scripts/match_tvprofil_channels.py
```

Matcher:

- uklanja `|BIH|`, `|HR|`, `|SR|` i slične prefikse pri poređenju
- ignoriše HD/FHD/UHD/4K oznake pri poređenju
- radi exact-normalized match prvo
- fuzzy match prihvata samo ako je rezultat dovoljno siguran i dovoljno bolji od drugog kandidata
- nesigurne rezultate označava kao `ambiguous`, umjesto da ih automatski koristi
- `not_found` se ne ubacuje u runtime konfiguraciju

Generiše:

`config/tvprofil_channels.runtime.json`

Statusi u CSV-u:

- `matched` — automatski dovoljno siguran
- `manual` — ručno potvrđen slug
- `ambiguous` — treba provjeriti
- `not_found` — nije pronađen
- `disabled` — ručno isključen

## 4. Dodaj TVProfil-only kanale u XMLTV

Ako kanal još ne postoji u `guide.xml`:

```bash
python3 scripts/ensure_tvprofil_channels.py guide.new.xml config/tvprofil_channels.runtime.json
```

Ovo dodaje samo XMLTV `<channel>` node; ne dodaje program dok importer ne uspješno preuzme raspored.

## 5. Preuzmi EPG

Postojeći importer sada se može koristiti sa generisanom konfiguracijom:

```bash
python3 scripts/import_tvprofil.py guide.new.xml config/tvprofil_channels.runtime.json
```

## Preporučeni tok

```text
M3U
 ↓
tvprofil_m3u.py
 ↓
tvprofil_playlist_channels.csv
 ↓
manual overrides + automatic matching
 ↓
tvprofil_channels.runtime.json
 ↓
ensure_tvprofil_channels.py
 ↓
import_tvprofil.py
 ↓
guide.xml
```

Automatski matcher nikada ne koristi `ambiguous` kanal za EPG. Takav kanal treba ručno potvrditi dodavanjem `tvprofil_slug` u override CSV.
