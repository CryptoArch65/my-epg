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
