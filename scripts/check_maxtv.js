#!/usr/bin/env node
// Manual MAXtv check: previous, current and next TV programme, plus channel logo.
const fs = require('node:fs/promises')
const path = require('node:path')
const crypto = require('node:crypto')
const { createRequire } = require('node:module')
const { selectPrograms } = require('./check_telemach')

const root = path.resolve(__dirname, '..')
const timezone = 'Europe/Zagreb'
const imageHost = 'https://tv-hr-prod.yo-digital.com'
// This public site parameter matches iptv-org's mojmaxtv channel adapter.
const catalogUrl = 'https://tv-hr-prod.yo-digital.com/hr-bifrost/epg/channel?channelMap_id=&includeVirtualChannels=false&natco_key=l2lyvGVbUm2EKJE96ImQgcc8PKMZWtbE&app_language=hr&natco_code=hr'
let axios, dayjs, maxtv

function loadUpstream() {
  const epgRequire = createRequire(path.join(root, 'epg', 'package.json'))
  axios = epgRequire('axios')
  dayjs = epgRequire('dayjs')
  dayjs.extend(epgRequire('dayjs/plugin/utc'))
  maxtv = epgRequire('./sites/mojmaxtv.hrvatskitelekom.hr/mojmaxtv.hrvatskitelekom.hr.config.js')
}

function validateChannels(input) {
  if (!Array.isArray(input?.channels) || input.channels.length < 1 || input.channels.length > 20) {
    throw new Error('config/epg-check.json mora sadržati 1–20 kanala')
  }
  const ids = new Set()
  return input.channels.map((channel, index) => {
    const name = typeof channel.name === 'string' ? channel.name.trim() : ''
    const site_id = String(channel.site_id ?? '').trim()
    if (!name || !/^\d+$/.test(site_id)) {
      throw new Error(`Kanal ${index + 1} treba name i brojčani MAXtv site_id, npr. 274913832105`)
    }
    if (ids.has(site_id)) throw new Error(`Ponovljeni site_id: ${site_id}`)
    ids.add(site_id)
    return { name, site_id }
  })
}

function freshHeaders() {
  const headers = { ...maxtv.request.headers }
  headers['x-call-time'] = Date.now()
  headers['x-request-tracking-id'] = crypto.randomUUID()
  headers['x-txn-id'] = crypto.createHash('sha256')
    .update([headers['x-request-tracking-id'], headers['x-request-session-id'], headers['device-id'], headers['x-call-time']].join(''))
    .digest('hex').slice(0, 32)
  return headers
}

async function getJson(url) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return (await axios.get(url, {
        headers: freshHeaders(), timeout: 30000, maxContentLength: 15000000
      })).data
    } catch (error) {
      if (attempt === 1) throw new Error(`MAXtv API nije dostupan: ${error.response?.status ?? error.message}`)
      await new Promise(resolve => setTimeout(resolve, 1200))
    }
  }
}

function normalisePrograms(responses, siteId) {
  const seen = new Set()
  return responses.flatMap(data => {
    const items = data?.channels?.[siteId]
    return Array.isArray(items) ? items : []
  }).map(item => ({
    title: item.description ?? item.episode_name ?? '',
    start: Date.parse(item.start_time),
    stop: Date.parse(item.end_time)
  })).filter(item => {
    const key = `${item.start}|${item.stop}|${item.title}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function resolveLogo(channel) {
  const images = Array.isArray(channel?.images) ? channel.images : []
  const candidate = channel?.logo_image_url ?? channel?.logo_url ?? channel?.channel_logo_url ??
    channel?.station_logo_url ?? channel?.logo?.url ?? channel?.logo?.path ??
    channel?.image?.url ?? channel?.image_url ?? images[0]?.url ?? images[0]?.path ?? null
  if (typeof candidate !== 'string' || !candidate.trim()) return null
  try {
    const url = new URL(candidate, imageHost)
    return ['https:', 'http:'].includes(url.protocol) ? url.toString() : null
  } catch { return null }
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
    const filename = `logos/maxtv-${siteId}.${ext}`
    await fs.writeFile(path.join(root, 'reports', filename), response.data)
    return filename
  } catch { return null }
}

function formatTime(milliseconds) {
  return new Intl.DateTimeFormat('hr-HR', {
    timeZone: timezone, day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(new Date(milliseconds))
}

function escapeMarkdown(value) {
  return String(value).replace(/\|/g, '\\|').replace(/[\r\n]+/g, ' ')
}

function describe(program) {
  return program ? `${escapeMarkdown(program.title)} (${formatTime(program.start)} – ${formatTime(program.stop)})` : 'Nema podataka'
}

async function getDay(date, offsets) {
  const responses = []
  for (let i = 0; i < offsets.length; i += 3) {
    const batch = offsets.slice(i, i + 3)
    const data = await Promise.all(batch.map(async offset => {
      const url = maxtv.url({ date }).replace('hour_offset=0', `hour_offset=${offset}`)
      const result = await getJson(url)
      if (!result?.channels || typeof result.channels !== 'object') {
        throw new Error('Neočekivan MAXtv EPG odgovor')
      }
      return result
    }))
    responses.push(...data)
  }
  return responses
}

async function main(config, { reportBase = 'epg-check' } = {}) {
  const channels = validateChannels(config)
  loadUpstream()
  const now = Date.now()
  const today = dayjs.utc(now).startOf('day')
  const offsets = [0, 3, 6, 9, 12, 15, 18, 21]
  const todayData = await getDay(today, offsets)
  const catalog = await getJson(catalogUrl)
  if (!Array.isArray(catalog?.channels)) throw new Error('Neočekivana MAXtv lista kanala')
  const byId = new Map(catalog.channels.map(channel => [String(channel.station_id), channel]))
  const missingBefore = channels.some(c => !selectPrograms(normalisePrograms(todayData, c.site_id), now).previous)
  const missingAfter = channels.some(c => !selectPrograms(normalisePrograms(todayData, c.site_id), now).next)
  // Adjacent UTC days cover broadcasts crossing midnight.
  const beforeData = missingBefore ? await getDay(today.subtract(1, 'day'), offsets) : []
  const afterData = missingAfter ? await getDay(today.add(1, 'day'), offsets) : []
  const responses = [...beforeData, ...todayData, ...afterData]
  await fs.mkdir(path.join(root, 'reports', 'logos'), { recursive: true })
  const results = []
  for (const channel of channels) {
    const details = byId.get(channel.site_id)
    const logoUrl = resolveLogo(details)
    const logoFile = await saveLogo(logoUrl, channel.site_id)
    const programs = normalisePrograms(responses, channel.site_id)
    const selected = selectPrograms(programs, now)
    const status = !details ? 'kanal nije pronađen' : programs.length ? 'ok' : 'nema programa'
    results.push({
      ...channel, source_name: details?.title ?? null, status,
      logo_url: logoUrl, logo_file: logoFile, ...selected
    })
    console.log(`${channel.site_id}: ${status}; trenutno: ${selected.current?.title ?? 'nema podataka'}`)
  }
  const report = [
    '# MAXtv EPG provjera', '',
    `Vrijeme provjere: ${formatTime(now)} (${timezone}).`, '',
    '| Kanal | site_id | Status | Prethodno | Trenutno | Sljedeće | Logo |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...results.map(r => `| ${escapeMarkdown(r.name)} | ${r.site_id} | ${r.status} | ${describe(r.previous)} | ${describe(r.current)} | ${describe(r.next)} | ${r.logo_url ? `[Otvori logo](${r.logo_url})` : 'Nema loga'} |`),
    '', ...results.flatMap(r => [
      `## ${escapeMarkdown(r.name)} (${r.site_id})`, '',
      r.logo_url ? `![Logo za ${escapeMarkdown(r.name)}](${r.logo_url})` : 'Logo nije pronađen u MAXtv podacima.', '',
      `Naziv u izvoru: ${escapeMarkdown(r.source_name ?? 'kanal nije pronađen')}. Status: ${r.status}.`, '',
      `- Prethodno: ${describe(r.previous)}`,
      `- Trenutno: ${describe(r.current)}`,
      `- Sljedeće: ${describe(r.next)}`, ''
    ])
  ].join('\n')
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.md`), report)
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.json`), JSON.stringify({
    source: 'maxtv', checked_at: new Date(now).toISOString(), timezone, channels: results
  }, null, 2))
  console.log(`Sačuvano ${results.length} MAXtv kanala u reports/${reportBase}.*`)
}

if (require.main === module) {
  fs.readFile(path.join(root, 'config', 'epg-check.json'), 'utf8')
    .then(text => main(JSON.parse(text)))
    .catch(error => { console.error(error.message); process.exitCode = 1 })
}
module.exports = { validateChannels, normalisePrograms, resolveLogo, main }
