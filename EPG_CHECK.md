# Ručna provjera EPG-a

Uredi [config/epg-check.json](config/epg-check.json), zatim otvori GitHub **Actions → Provjera EPG izvora → Run workflow**. Rezultat je u **Job summary**; kompletan Markdown, JSON i dostupni logotipi su u artefaktu **epg-provjera**.

Polje `source` bira jedan od podržanih izvora:

- `"mtel"`: IPTV vodič na `https://mtel.ba/Televizija/TV-ponuda/TV-vodic#tv-iptv`. Za svaki kanal unesi željeni `name` i puni `site_id` iz m:tel IPTV tabele, npr. `"iptv#ch-15-bht"`.
- `"telemach"`: `https://epg.telemach.ba/`. Za svaki kanal unesi `name`, brojčani `site_id` i `country` (`"ba"` ili `"me"`).

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

m:tel ID nije zamjenjiv s Telemach ID-jem. Polje `name` slobodno promijeni: služi za prikaz u izvještaju i ne mijenja naziv kanala u IPTV listi. `site_id` identifikuje kanal u odabranom izvoru.

URL TV vodiča ne mijenja se u konfiguraciji: adresa stranice nije direktni API za emisije. Izbor `source` bira odgovarajući EPG adapter i njegov URL za podatke. Za novi domen/URL potreban je novi adapter koji razumije njegov format. Lista m:tel `site_id` iz prethodnog Excela je snimak projekta iptv-org/epg; pojedini kanali mogu biti zastarjeli ili bez podataka u aktuelnom EPG-u.
