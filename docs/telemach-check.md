# Provjera Telemach EPG kanala

U [config/telemach-check.json](../config/telemach-check.json) promijeni `name`, `site_id` i `country` za željene kanale. `country` može biti `ba` ili `me`; `site_id` ostavi pod navodnicima. Početna lista ima pet kanala, ali skripta podržava 1–20.

ID-jeve možeš naći u listama [BiH](https://github.com/iptv-org/epg/blob/master/sites/epg.telemach.ba/epg.telemach.ba_ba.channels.xml) i [Crne Gore](https://github.com/iptv-org/epg/blob/master/sites/epg.telemach.ba/epg.telemach.ba_me.channels.xml). Ime služi za prikaz u izvještaju; `site_id` i `country` određuju koji se podaci povlače.

Na GitHubu otvori **Actions → Provjera Telemach EPG → Run workflow**. Rezultate ćeš vidjeti u sažetku runa. Preuzmi artefakt **telemach-epg-provjera** ako želiš i JSON, Markdown izvještaj te kopije dostupnih logotipa. Vrijeme se prikazuje u zoni Europe/Sarajevo. Provjera čita Telemachove podatke u trenutku pokretanja i ne mijenja objavljeni `guide.xml`.
