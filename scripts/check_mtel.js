#!/usr/bin/env node
// Manual check of m:tel IPTV previous, current and next EPG entries.
const fs = require('node:fs/promises')
const path = require('node:path')
const { createRequire } = require('node:module')
const { selectPrograms } = require('./check_telemach')

const root = path.resolve(__dirname, '..')
const timezone = 'Europe/Sarajevo'
let axios, dayjs, mtel

function loadUpstream() {
  const epgRequire = createRequire(path.join(root, 'epg', 'package.json'))
  axios = epgRequire('axios')
  dayjs = epgRequire('dayjs')
  dayjs.extend(epgRequire('dayjs/plugin/utc'))
  dayjs.extend(epgRequire('dayjs/plugin/timezone'))
  mtel = epgRequire('./sites/mtel.ba/mtel.ba.config.js')
}

function validateChannels(input) {
  if (!Array.isArray(input?.channels) || input.channels.length < 1 || input.channels.length > 20) {
    throw new Error('config/epg-check.json mora sadržati 1–20 kanala')
  }
  const ids = new Set()
  return input.channels.map((channel, index) => {
    const name = typeof channel.name === 'string' ? channel.name.trim() : ''
    const site_id = String(channel.site_id ?? '').trim()
    if (!name || !/^iptv#ch-[a-z0-9-]+$/i.test(site_id)) {
      throw new Error(`Kanal ${index + 1} treba name i m:tel IPTV site_id, npr. iptv#ch-15-bht`)
    }
    if (ids.has(site_id)) throw new Error(`Ponovljeni site_id: ${site_id}`)
    ids.add(site_id)
    return { name, site_id }
  })
}

function normalisePrograms(programs) {
  const seen = new Set()
  return programs.map(p => ({ title: p.title, start: p.start.valueOf(), stop: p.stop.valueOf() }))
    .filter(p => {
      const key = `${p.start}|${p.stop}|${p.title}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function resolveLogo(product) {
  const images = Array.isArray(product?.images) ? product.images : []
  const candidate = product?.picture?.url ?? product?.logo?.url ?? product?.image?.url ??
    product?.thumbnail?.url ?? images[0]?.url ?? null
  if (!candidate || typeof candidate !== 'string') return null
  try {
    const url = new URL(candidate, 'https://mtel.ba')
    return ['https:', 'http:'].includes(url.protocol) ? url.toString() : null
  } catch { return null }
}

function formatTime(ms) {
  return new Intl.DateTimeFormat('bs-BA', {
    timeZone: timezone, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(new Date(ms))
}

function escapeMarkdown(s) {
  return String(s).replace(/\|/g, '\\|').replace(/[\r\n]+/g, ' ')
}

function describe(p) {
  return p ? `${escapeMarkdown(p.title)} (${formatTime(p.start)} – ${formatTime(p.stop)})` : 'Nema podataka'
}

async function getJson(url) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const data = (await axios.get(url, { timeout: 30000, maxContentLength: 10000000 })).data
      if (!Array.isArray(data?.products)) throw new Error('Neočekivan m:tel EPG odgovor')
      return data
    } catch (error) {
      if (attempt === 1) throw new Error(`m:tel EPG nije dostupan: ${error.response?.status ?? error.message}`)
      await new Promise(resolve => setTimeout(resolve, 1200))
    }
  }
}

async function saveLogo(url, siteId) {
  if (!url) return null
  try {
    const response = await axios.get(url, { responseType: 'arraybuffer', timeout: 20000, maxContentLength: 5000000 })
    const type = response.headers['content-type'] ?? ''
    const ext = type.includes('png') ? 'png' : type.includes('webp') ? 'webp' : type.includes('svg') ? 'svg' : type.includes('jpeg') ? 'jpg' : null
    if (!ext) return null
    const filename = `logos/mtel-${siteId.split('#')[1]}.${ext}`
    await fs.writeFile(path.join(root, 'reports', filename), response.data)
    return filename
  } catch { return null }
}

async function main(config, { reportBase = 'epg-check' } = {}) {
  const channels = validateChannels(config)
  loadUpstream()
  const now = Date.now()
  const today = dayjs(now).tz(timezone).startOf('day')
  const days = [-1, 0, 1]
  // One request per day includes all IPTV channels; reuse it for every selected channel.
  const responses = await Promise.all(days.map(offset => {
    const url = mtel.url({ channel: channels[0], date: today.add(offset, 'day') })
    return getJson(url)
  }))
  if (responses.every(r => r.products.length === 0)) throw new Error('m:tel EPG vratio je praznu listu kanala')
  // Catalog metadata may contain channel logos missing from the EPG response.
  const catalogUrl = 'https://mtel.ba/hybris/ecommerce/b2c/v1/products/channels/search?pageSize=999&query=:relevantno:tv-kategorija:tv-iptv'
  const catalog = await getJson(catalogUrl).then(data => new Map(data.products.map(p => [p.code, p])))
    .catch(error => { console.warn(`m:tel katalog logotipa nije dostupan: ${error.message}`); return new Map() })
  await fs.mkdir(path.join(root, 'reports', 'logos'), { recursive: true })
  const results = []
  for (const channel of channels) {
    const code = channel.site_id.split('#')[1]
    const products = responses.map(data => data.products.find(p => p.code === code)).filter(Boolean)
    const details = catalog.get(code)
    const logoUrl = resolveLogo(details) ?? resolveLogo(products[1] ?? products[0])
    const logoFile = await saveLogo(logoUrl, channel.site_id)
    const programs = normalisePrograms(responses.flatMap(data => mtel.parser({
      content: JSON.stringify(data), channel
    })))
    const selected = selectPrograms(programs, now)
    const result = {
      ...channel, source_name: details?.name ?? products[1]?.name ?? products[0]?.name ?? null,
      status: products.length ? (programs.length ? 'ok' : 'nema programa') : 'kanal nije pronađen',
      logo_url: logoUrl, logo_file: logoFile, ...selected
    }
    results.push(result)
    console.log(`${channel.site_id}: ${result.status}; trenutno: ${selected.current?.title ?? 'nema podataka'}`)
  }
  const report = [
    '# m:tel IPTV EPG provjera', '',
    `Vrijeme provjere: ${formatTime(now)} (${timezone}).`, '',
    '| Kanal | site_id | Status | Prethodno | Trenutno | Sljedeće | Logo |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...results.map(r => `| ${escapeMarkdown(r.name)} | ${r.site_id} | ${r.status} | ${describe(r.previous)} | ${describe(r.current)} | ${describe(r.next)} | ${r.logo_url ? `[Otvori logo](${r.logo_url})` : 'Nema loga'} |`),
    '', ...results.flatMap(r => [
      `## ${escapeMarkdown(r.name)} (${r.site_id})`, '',
      r.logo_url ? `![Logo za ${escapeMarkdown(r.name)}](${r.logo_url})` : 'Logo nije pronađen u m:tel EPG podacima.', '',
      `Naziv u izvoru: ${escapeMarkdown(r.source_name ?? 'kanal nije pronađen')}. Status: ${r.status}.`, '',
      `- Prethodno: ${describe(r.previous)}`,
      `- Trenutno: ${describe(r.current)}`,
      `- Sljedeće: ${describe(r.next)}`, ''
    ])
  ].join('\n')
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.md`), report)
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.json`), JSON.stringify({
    source: 'mtel', checked_at: new Date(now).toISOString(), timezone, channels: results
  }, null, 2))
  console.log(`Sačuvano ${results.length} m:tel kanala u reports/${reportBase}.*`)
}

if (require.main === module) {
  fs.readFile(path.join(root, 'config', 'epg-check.json'), 'utf8')
    .then(text => main(JSON.parse(text)))
    .catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = { validateChannels, normalisePrograms, resolveLogo, main }
