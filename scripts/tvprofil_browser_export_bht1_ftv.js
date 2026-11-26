/*
 * Paste this file into the console on an already open TvProfil page.
 * It downloads an XMLTV test file; it never sends data to GitHub.
 * This version exports only the confirmed BHT1 and FTV channels.
 */
(async () => {
  const channels = [
    {xmltv_id: "bht1", slug: "bht1", display_name: "BHT1"},
    {xmltv_id: "ftv", slug: "ftv", display_name: "FTV"}
  ];
  if (typeof bazinga !== "function" || typeof Tvprofil === "undefined") {
    throw new Error("Otvori TvProfil stranicu sa aktivnom sesijom prije pokretanja.");
  }
  if (!channels.length || channels.some(c => !c.xmltv_id || !c.slug)) {
    throw new Error("Svaki kanal mora imati xmltv_id i potvrđen TvProfil slug.");
  }
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"
  })[c]);
  const xmlDate = seconds => new Date(seconds * 1000).toISOString()
    .replace(/[-:T]/g, "").slice(0, 14) + " +0000";
  const day = offset => {
    const now = new Date();
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/Zagreb", year: "numeric", month: "2-digit", day: "2-digit"
    }).formatToParts(now);
    const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
    const d = new Date(Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day) + offset));
    return d.toISOString().slice(0, 10);
  };
  async function fetchDay(slug, datum) {
    const data = {datum, kanal: slug};
    bazinga(data);
    const bKey = Object.keys(data).find(k => /^b\d+$/.test(k));
    if (!bKey) throw new Error(`TvProfil ključ nije pronađen: ${slug} ${datum}`);
    const callback = "tvprogram" + (Tvprofil.config?.lang || "") + bKey;
    const params = new URLSearchParams({callback, datum, kanal: slug});
    params.set(bKey, data[bKey]);
    const response = await fetch("/tvprogram/program/?" + params, {
      credentials: "include",
      headers: {"X-Requested-With": "XMLHttpRequest", "Accept": "text/javascript, application/javascript, application/json, */*"}
    });
    if (!response.ok) throw new Error(`${slug} ${datum}: HTTP ${response.status}`);
    const raw = await response.text();
    const match = raw.match(/^[^(]+\(([\s\S]*)\)\s*;?\s*$/);
    if (!match) throw new Error(`${slug} ${datum}: JSONP nije prepoznat`);
    const json = JSON.parse(match[1]);
    if (json.code !== 0) throw new Error(`${slug} ${datum}: code ${json.code}`);
    const container = document.createElement("div");
    container.innerHTML = json.data?.program || "";
    return [...container.querySelectorAll(".row[data-ts][data-len]")].map(row => ({
      ts: Number(row.dataset.ts), len: Number(row.dataset.len),
      title: row.querySelector("a")?.textContent?.replace(/\s+/g, " ").trim() || "",
      category: row.querySelector("small")?.textContent?.replace(/\s+/g, " ").trim() || "",
      image: row.dataset.image || ""
    }));
  }
  const programmes = [];
  const seen = new Set();
  const counts = {};
  const missingTitles = [];
  for (const channel of channels) {
    let count = 0;
    for (let offset = -7; offset <= 5; offset++) {
      const datum = day(offset);
      const events = await fetchDay(channel.slug, datum);
      for (const event of events) {
        if (!Number.isFinite(event.ts) || !Number.isFinite(event.len) || event.len <= 0) {
          console.error("Nevažeći red iz TvProfila", {channel: channel.slug, datum, event});
          throw new Error(`Nevažeći program: ${channel.slug} ${datum}; pogledaj prethodni zapis u konzoli`);
        }
        if (!event.title) {
          missingTitles.push({channel: channel.slug, datum, ts: event.ts, len: event.len});
          continue;
        }
        const key = `${channel.xmltv_id}:${event.ts}:${event.len}:${event.title}`;
        if (seen.has(key)) continue;
        seen.add(key);
        programmes.push({channel, ...event});
        count++;
      }
    }
    if (!count) throw new Error(`Nema programa za ${channel.slug}; XML nije sačuvan.`);
    counts[channel.xmltv_id] = count;
    console.log(channel.xmltv_id, count);
  }
  const xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv generator-info-name="TVProfil browser test">'];
  for (const c of channels) {
    xml.push(`  <channel id="${esc(c.xmltv_id)}"><display-name>${esc(c.display_name || c.xmltv_id)}</display-name></channel>`);
  }
  for (const e of programmes.sort((a, b) => a.ts - b.ts)) {
    xml.push(`  <programme channel="${esc(e.channel.xmltv_id)}" start="${xmlDate(e.ts)}" stop="${xmlDate(e.ts + e.len)}">`);
    xml.push(`    <title lang="hr">${esc(e.title)}</title>`);
    if (e.category) xml.push(`    <category lang="hr">${esc(e.category)}</category>`);
    if (e.image) xml.push(`    <icon src="${esc(e.image)}"/>`);
    xml.push("  </programme>");
  }
  xml.push("</tv>");
  const blob = new Blob([xml.join("\n") + "\n"], {type: "application/xml;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `tvprofil-bht1-ftv-${day(0)}.xml`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  console.log("XMLTV sačuvan:", programmes.length, "programa", counts);
  if (missingTitles.length) {
    console.warn(`Preskočeno ${missingTitles.length} redova bez naslova (nisu u XML-u):`, missingTitles);
  }
})();
