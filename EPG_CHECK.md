# Ručna provjera EPG-a

Uredi [config/epg-check.json](config/epg-check.json), zatim otvori GitHub **Actions → Provjera EPG izvora → Run workflow**. Rezultat je u **Job summary**; kompletan Markdown, JSON i dostupni logotipi su u artefaktu **epg-provjera**.

Polje `source` bira jedan od podržanih izvora:

- `"mtel"`: IPTV vodič na `https://mtel.ba/Televizija/TV-ponuda/TV-vodic#tv-iptv`. Za svaki kanal unesi željeni `name` i puni `site_id` iz m:tel IPTV tabele, npr. `"iptv#ch-15-bht"`.
- `"telemach"`: `https://epg.telemach.ba/`. Za svaki kanal unesi `name`, brojčani `site_id` i `country` (`"ba"` ili `"me"`).
- `"maxtv"`: `https://mojmaxtv.hrvatskitelekom.hr/epg`. Za svaki kanal unesi `name` i brojčani `site_id` iz prethodne MAXtv Excel tabele ili [liste MAXtv kanala](https://github.com/iptv-org/epg/blob/master/sites/mojmaxtv.hrvatskitelekom.hr/mojmaxtv.hrvatskitelekom.hr.channels.xml). `country` nije potreban.

Primjer za m:tel:

```json
{
  "source": "mtel",
  "channels": [
    { "name": "|BIH| BHT 1 HD", "site_id": "iptv#ch-15-bht" }
  ]
}
```

Primjer za Telemach:

```json
{
  "source": "telemach",
  "channels": [
    { "name": "OBN (BIH)", "site_id": "30", "country": "ba" }
  ]
}
```

m:tel, Telemach i MAXtv ID-jevi nisu međusobno zamjenjivi. Polje `name` slobodno promijeni: služi za prikaz u izvještaju i ne mijenja naziv kanala u IPTV listi. `site_id` identifikuje kanal u odabranom izvoru.

Primjer za MAXtv:

```json
{
  "source": "maxtv",
  "channels": [
    { "name": "HRT 1 HD", "site_id": "274913832105" },
    { "name": "RTL", "site_id": "274913832109" }
  ]
}
```

Za MAXtv se prikazuje vrijeme prema Hrvatskoj (`Europe/Zagreb`). Uredi `name` kako želiš, a `site_id` kopiraj kao tekst bez skraćivanja iz tabele. Jedna provjera podržava 1–20 kanala. Status `kanal nije pronađen` znači da ID više nije u trenutnoj listi MAXtv.

URL TV vodiča ne mijenja se u konfiguraciji: adresa stranice nije direktni API za emisije. Izbor `source` bira odgovarajući EPG adapter i njegov URL za podatke. Za novi domen/URL potreban je novi adapter koji razumije njegov format. Lista m:tel `site_id` iz prethodnog Excela je snimak projekta iptv-org/epg; pojedini kanali mogu biti zastarjeli ili bez podataka u aktuelnom EPG-u.
