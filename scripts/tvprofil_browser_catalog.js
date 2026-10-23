/* Paste into the console while https://tvprofil.com/box/ is open. */
(() => {
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const entries = new Map();
  const slugFrom = value => {
    const raw = clean(value);
    const link = raw.match(/\/tvprogram\/(?:program\/)?kanal\/([^/?#]+)/);
    const slug = decodeURIComponent(link ? link[1] : raw);
    return /^[a-z][a-z0-9_-]{2,}$/i.test(slug) ? slug : "";
  };
  function add(name, value) {
    const slug = slugFrom(value);
    name = clean(name);
    if (!name || !slug || name.length > 120) return;
    entries.set(`${name}\0${slug}`, {name, slug});
  }
  function values(el) {
    return ["data-kanal", "data-channel", "data-slug", "value", "href"]
      .map(attr => el.getAttribute(attr)).filter(Boolean);
  }
  const elements = document.querySelectorAll("input,option,a[href*='/tvprogram/'],[data-kanal],[data-channel],[data-slug]");
  for (const el of elements) {
    const label = el.labels?.[0] || el.closest("label") || (el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null);
    const name = clean(label?.textContent || el.textContent || el.getAttribute("title") || el.getAttribute("aria-label"));
    for (const value of values(el)) add(name, value);
  }
  for (const label of document.querySelectorAll("label[for]")) {
    const el = document.getElementById(label.htmlFor);
    if (el) for (const value of values(el)) add(label.textContent, value);
  }
  // /box/ stores most channels as plain <div data-id="123">Name</div>.
  // This numeric ID is useful for name matching but is NOT a schedule slug.
  for (const el of document.querySelectorAll(".channels [data-id]")) {
    const name = clean(el.textContent);
    const id = el.getAttribute("data-id");
    if (!name || !/^\d+$/.test(id) || name.length > 120) continue;
    entries.set(`${name}\0id:${id}`, {name, id});
  }
  const catalog = [...entries.values()].sort((a, b) => a.name.localeCompare(b.name));
  if (!catalog.length) {
    console.log("Nema pronađenih kanala. Stranica:", location.href,
      "Primjer kontrola:", [...elements].slice(0, 8).map(el => el.outerHTML.slice(0, 300)));
    throw new Error("TvProfil katalog nije pronađen na ovoj stranici.");
  }
  const blob = new Blob([JSON.stringify(catalog, null, 2) + "\n"], {type: "application/json"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "tvprofil-catalog.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  console.log(`Sačuvan TvProfil katalog: ${catalog.length} kandidata (numerički ID nije slug)`, catalog.slice(0, 12));
})();
