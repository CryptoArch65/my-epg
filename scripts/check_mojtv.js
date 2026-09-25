#!/usr/bin/env node
// Manual check of MojTV.net's documented per-channel XMLTV service.
const fs = require('node:fs/promises')
const path = require('node:path')
const { createRequire } = require('node:module')
const { selectPrograms } = require('./check_telemach')

const root = path.resolve(__dirname, '..')
const timezone = 'Europe/Belgrade'
let axios, cheerio

function loadUpstream() {
  const epgRequire = createRequire(path.join(root, 'epg', 'package.json'))
  axios = epgRequire('axios')
  cheerio = epgRequire('cheerio')
}

function validateChannels(config) {
  if (!Array.isArray(config?.channels) || config.channels.length < 1 || config.channels.length > 20) {
    throw new Error('config/epg-check.json mora sadržati 1–20 kanala')
  }
  const ids = new Set()
  return config.channels.map((channel, i) => {
    const name = typeof channel.name === 'string' ? channel.name.trim() : ''
    const site_id = String(channel.site_id ?? '').trim()
    if (!name || !/^\d+$/.test(site_id)) {
      throw new Error(`Kanal ${i + 1} treba name i brojčani MojTV site_id, npr. 31 za B92`)
    }
    if (ids.has(site_id)) throw new Error(`Ponovljeni site_id: ${site_id}`)
    ids.add(site_id)
    return { name, site_id }
  })
}

function dateForOffset(now, offset) {
  const values = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: timezone, day: 'numeric', month: 'numeric', year: 'numeric'
  }).formatToParts(new Date(now)).map(part => [part.type, Number(part.value)]))
  const day = new Date(Date.UTC(values.year, values.month - 1, values.day + offset))
  return `${day.getUTCDate()}.${day.getUTCMonth() + 1}.${day.getUTCFullYear()}.`
}

function xmltvTime(value) {
  const m = String(value ?? '').trim().match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?\s*([+-])(\d{2})(\d{2})$/)
  if (!m) return NaN
  const offset = (m[7] === '+' ? 1 : -1) * (Number(m[8]) * 60 + Number(m[9]))
  return Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]),
    Number(m[4]), Number(m[5]), Number(m[6] ?? 0)) - offset * 60000
}

function parseXmltv(content) {
  if (!/<tv\b/i.test(content)) throw new Error('MojTV nije vratio XMLTV raspored')
  const $ = cheerio.load(content, { xmlMode: true })
  const programs = []
  $('programme').each((_i, node) => {
    const p = $(node)
    const title = p.find('title').first().text().trim()
    const start = xmltvTime(p.attr('start'))
    const stop = xmltvTime(p.attr('stop'))
    if (title && Number.isFinite(start) && Number.isFinite(stop) && start < stop) {
      programs.push({ title, start, stop })
    }
  })
  const logo = $('channel icon').first().attr('src') ?? null
  const sourceName = $('channel display-name').first().text().trim() || null
  return { programs, logo, sourceName }
}

function resolveLogo(candidate) {
  if (typeof candidate !== 'string') return null
  try {
    const url = new URL(candidate, 'https://mojtv.net')
    return ['https:', 'http:'].includes(url.protocol) ? url.toString() : null
  } catch { return null }
}

async function getDay(siteId, date) {
  const url = `https://mojtv.net/xmltv/service.ashx?kanal_id=${encodeURIComponent(siteId)}&date=${encodeURIComponent(date)}`
  let content
  try {
    const response = await axios.get(url, {
      timeout: 30000, maxContentLength: 10000000, responseType: 'text',
      headers: { Accept: 'application/xml,text/xml,*/*', 'User-Agent': 'Mozilla/5.0' }
    })
    content = response.data
  } catch (error) {
    throw new Error(`MojTV XMLTV za ${siteId} (${date}) nije dostupan: ${error.response?.status ?? error.message}`)
  }
  return parseXmltv(content)
}

async function saveLogo(url, siteId) {
  if (!url) return null
  try {
    const response = await axios.get(url, {
      responseType: 'arraybuffer', timeout: 20000, maxContentLength: 5000000
    })
    const type = response.headers['content-type'] ?? ''
    const ext = type.includes('png') ? 'png' : type.includes('webp') ? 'webp'
      : type.includes('svg') ? 'svg' : type.includes('jpeg') ? 'jpg' : null
    if (!ext) return null
    const file = `logos/mojtv-${siteId}.${ext}`
    await fs.writeFile(path.join(root, 'reports', file), response.data)
    return file
  } catch { return null }
}

function formatTime(ms) {
  return new Intl.DateTimeFormat('sr-Latn-RS', {
    timeZone: timezone, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(new Date(ms))
}

function escapeMarkdown(value) {
  return String(value).replace(/\|/g, '\\|').replace(/[\r\n]+/g, ' ')
}

function describe(program) {
  return program ? `${escapeMarkdown(program.title)} (${formatTime(program.start)} – ${formatTime(program.stop)})` : 'Nema podataka'
}

async function main(config, { reportBase = 'epg-check' } = {}) {
  const channels = validateChannels(config)
  loadUpstream()
  const now = Date.now()
  await fs.mkdir(path.join(root, 'reports', 'logos'), { recursive: true })
  const results = []
  for (const channel of channels) {
    const today = await getDay(channel.site_id, dateForOffset(now, 0))
    let selected = selectPrograms(today.programs, now)
    const adjacent = []
    if (!selected.previous) adjacent.push(await getDay(channel.site_id, dateForOffset(now, -1)))
    if (!selected.next) adjacent.push(await getDay(channel.site_id, dateForOffset(now, 1)))
    const seen = new Set()
    const programs = [today, ...adjacent].flatMap(day => day.programs).filter(p => {
      const key = `${p.start}|${p.stop}|${p.title}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    selected = selectPrograms(programs, now)
    const logoUrl = resolveLogo(today.logo ?? adjacent.find(day => day.logo)?.logo)
    const logoFile = await saveLogo(logoUrl, channel.site_id)
    const status = programs.length ? (selected.current ? 'ok' : 'nema emisije sada') : 'nema programa'
    results.push({
      ...channel, source_name: today.sourceName, status,
      logo_url: logoUrl, logo_file: logoFile, ...selected
    })
    console.log(`${channel.site_id}: ${status}; trenutno: ${selected.current?.title ?? 'nema podataka'}`)
  }
  if (results.every(r => !r.current)) throw new Error('MojTV nije vratio nijednu trenutnu emisiju; izvještaj nije objavljen')
  const report = [
    '# MojTV.net EPG provjera', '',
    `Vrijeme provjere: ${formatTime(now)} (${timezone}).`, '',
    '| Kanal | site_id | Status | Prethodno | Trenutno | Sljedeće | Logo |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...results.map(r => `| ${escapeMarkdown(r.name)} | ${r.site_id} | ${r.status} | ${describe(r.previous)} | ${describe(r.current)} | ${describe(r.next)} | ${r.logo_url ? `[Otvori logo](${r.logo_url})` : 'Nema loga'} |`),
    '', ...results.flatMap(r => [
      `## ${escapeMarkdown(r.name)} (${r.site_id})`, '',
      r.logo_url ? `![Logo za ${escapeMarkdown(r.name)}](${r.logo_url})` : 'Logo nije dostupan.', '',
      `Naziv u izvoru: ${escapeMarkdown(r.source_name ?? 'nije naveden')}. Status: ${r.status}.`, '',
      `- Prethodno: ${describe(r.previous)}`,
      `- Trenutno: ${describe(r.current)}`,
      `- Sljedeće: ${describe(r.next)}`, ''
    ])
  ].join('\n')
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.md`), report)
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.json`), JSON.stringify({
    source: 'mojtv', checked_at: new Date(now).toISOString(), timezone, channels: results
  }, null, 2))
  console.log(`Sačuvano ${results.length} MojTV kanala u reports/${reportBase}.*`)
}

if (require.main === module) {
  fs.readFile(path.join(root, 'config', 'epg-check.json'), 'utf8')
    .then(text => main(JSON.parse(text)))
    .catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = { validateChannels, dateForOffset, xmltvTime, parseXmltv, main }
