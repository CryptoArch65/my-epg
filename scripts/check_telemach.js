#!/usr/bin/env node
// Manual check of Telemach's previous, current and next EPG entries.
const fs = require('node:fs/promises')
const path = require('node:path')
const { createRequire } = require('node:module')

const root = path.resolve(__dirname, '..')
let axios, dayjs, telemach

function loadUpstream() {
  const epgRequire = createRequire(path.join(root, 'epg', 'package.json'))
  axios = epgRequire('axios')
  dayjs = epgRequire('dayjs')
  dayjs.extend(epgRequire('dayjs/plugin/utc'))
  telemach = epgRequire('./sites/epg.telemach.ba/epg.telemach.ba.config.js')
}

const imageHost = 'https://images-web.ug-be.cdn.united.cloud'

function validateChannels(input) {
  if (!Array.isArray(input?.channels) || input.channels.length < 1 || input.channels.length > 20) {
    throw new Error('config/telemach-check.json must contain 1–20 channels')
  }
  return input.channels.map((channel, index) => {
    const name = channel.name?.trim()
    const site_id = String(channel.site_id ?? '').trim()
    const country = channel.country
    if (!name || !/^\d+$/.test(site_id) || !['ba', 'me'].includes(country)) {
      throw new Error(`Channel ${index + 1} needs a name, numeric site_id and country ba/me`)
    }
    return { name, site_id, country }
  })
}

function selectPrograms(programs, now) {
  const valid = programs
    .filter(p => p.title && Number.isFinite(p.start) && Number.isFinite(p.stop) && p.start < p.stop)
    .sort((a, b) => a.start - b.start || a.stop - b.stop)
  const current = valid.filter(p => p.start <= now && now < p.stop).at(-1) ?? null
  const previous = current
    ? valid.filter(p => p.stop <= current.start).sort((a, b) => a.stop - b.stop).at(-1) ?? null
    : valid.filter(p => p.stop <= now).sort((a, b) => a.stop - b.stop).at(-1) ?? null
  const next = current
    ? valid.find(p => p.start >= current.stop) ?? null
    : valid.find(p => p.start > now) ?? null
  return { previous, current, next }
}

function resolveLogo(channel) {
  const images = Array.isArray(channel?.images) ? channel.images : []
  const preferred = images.find(i => /logo|channel/i.test(`${i.type ?? ''} ${i.name ?? ''} ${i.category ?? ''}`)) ?? images[0]
  const candidate = preferred?.path ?? preferred?.url ?? channel?.logo?.path ?? channel?.logoUrl ?? channel?.logo
  if (!candidate || typeof candidate !== 'string') return null
  const url = new URL(candidate, imageHost)
  return ['https:', 'http:'].includes(url.protocol) ? url.toString() : null
}

function formatTime(milliseconds) {
  return new Intl.DateTimeFormat('bs-BA', {
    timeZone: 'Europe/Sarajevo', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).format(new Date(milliseconds))
}

function escapeMarkdown(value) {
  return String(value).replace(/\|/g, '\\|').replace(/[\r\n]+/g, ' ')
}

async function getJson(url, headers) {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return (await axios.get(url, { headers, timeout: 30000 })).data
    } catch (error) {
      if (attempt === 1) throw new Error(`Telemach API returned ${error.response?.status ?? error.code ?? 'an error'}`)
      await new Promise(resolve => setTimeout(resolve, 1200))
    }
  }
}

async function getChannelCatalog(country, headers) {
  const communityId = country === 'me' ? 5 : 12
  const languageId = country === 'me' ? 10001 : 59
  const url = `https://api-web.ug-be.cdn.united.cloud/v1/public/channels?channelType=TV&communityId=${communityId}&languageId=${languageId}&imageSize=L`
  const data = await getJson(url, headers)
  if (!Array.isArray(data)) throw new Error(`Unexpected channel response for ${country}`)
  return new Map(data.map(channel => [String(channel.id), channel]))
}

async function getPrograms(channel, headers, now) {
  // Include adjacent days so a show crossing midnight has neighbors.
  const today = dayjs.utc(now).startOf('day')
  const days = [-1, 0, 1]
  const responses = await Promise.all(days.map(async offset => {
    const url = telemach.url({ channel, date: today.add(offset, 'day'), country: channel.country })
    const data = await getJson(url, headers)
    return telemach.parser({ content: JSON.stringify(data) })
  }))
  const seen = new Set()
  return responses.flat().map(program => ({
    title: program.title, start: program.start.valueOf(), stop: program.stop.valueOf()
  })).filter(program => {
    const key = `${program.start}|${program.stop}|${program.title}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

async function saveLogo(url, country, siteId) {
  if (!url) return null
  try {
    const response = await axios.get(url, { responseType: 'arraybuffer', timeout: 20000, maxContentLength: 5000000 })
    const type = response.headers['content-type'] ?? ''
    const ext = type.includes('png') ? 'png' : type.includes('webp') ? 'webp' : type.includes('svg') ? 'svg' : type.includes('jpeg') ? 'jpg' : null
    if (!ext) return null
    const filename = `logos/${country}-${siteId}.${ext}`
    await fs.writeFile(path.join(root, 'reports', filename), response.data)
    return filename
  } catch {
    return null
  }
}

function describe(program) {
  return program ? `${escapeMarkdown(program.title)} (${formatTime(program.start)} – ${formatTime(program.stop)})` : 'Nema podataka'
}

async function main({ configPath = path.join(root, 'config', 'telemach-check.json'), reportBase = 'telemach-check' } = {}) {
  loadUpstream()
  const config = validateChannels(JSON.parse(await fs.readFile(configPath, 'utf8')))
  const now = Date.now()
  await fs.mkdir(path.join(root, 'reports', 'logos'), { recursive: true })
  const headersByCountry = new Map()
  const catalogByCountry = new Map()
  const results = []

  for (const channel of config) {
    if (!headersByCountry.has(channel.country)) {
      const headers = await telemach.request.headers({ country: channel.country })
      if (!headers?.Authorization) throw new Error(`Could not authenticate to Telemach (${channel.country})`)
      headersByCountry.set(channel.country, headers)
      catalogByCountry.set(channel.country, await getChannelCatalog(channel.country, headers))
    }
    const headers = headersByCountry.get(channel.country)
    const details = catalogByCountry.get(channel.country).get(channel.site_id)
    const logoUrl = resolveLogo(details)
    const logoFile = await saveLogo(logoUrl, channel.country, channel.site_id)
    const programs = await getPrograms(channel, headers, now)
    const selected = selectPrograms(programs, now)
    results.push({ ...channel, source_name: details?.name ?? null, logo_url: logoUrl, logo_file: logoFile, ...selected })
    console.log(`${channel.country}/${channel.site_id}: ${selected.current?.title ?? 'no current programme'}, logo ${logoUrl ? 'found' : 'missing'}`)
  }

  const report = [
    '# Telemach EPG provjera',
    '',
    `Vrijeme provjere: ${formatTime(now)} (Europe/Sarajevo).`,
    '',
    '| Kanal | Regija | site_id | Prethodno | Trenutno | Sljedeće | Logo |',
    '| --- | --- | --- | --- | --- | --- | --- |',
    ...results.map(r => `| ${escapeMarkdown(r.name)} | ${r.country.toUpperCase()} | ${r.site_id} | ${describe(r.previous)} | ${describe(r.current)} | ${describe(r.next)} | ${r.logo_url ? `[Otvori logo](${r.logo_url})` : 'Nema loga'} |`),
    '',
    ...results.flatMap(r => [
      `## ${escapeMarkdown(r.name)} (${r.country.toUpperCase()}, site_id ${r.site_id})`,
      '',
      r.logo_url ? `![Logo za ${escapeMarkdown(r.name)}](${r.logo_url})` : 'Logo nije pronađen u Telemach podacima.',
      '',
      `Naziv u izvoru: ${escapeMarkdown(r.source_name ?? 'kanal nije u aktuelnoj listi')}.`,
      '',
      `- Prethodno: ${describe(r.previous)}`,
      `- Trenutno: ${describe(r.current)}`,
      `- Sljedeće: ${describe(r.next)}`,
      ''
    ])
  ].join('\n')
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.md`), report)
  await fs.writeFile(path.join(root, 'reports', `${reportBase}.json`), JSON.stringify({ checked_at: new Date(now).toISOString(), timezone: 'Europe/Sarajevo', channels: results }, null, 2))
  console.log(`Saved ${results.length} channel checks to reports/`)
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1 })
module.exports = { validateChannels, selectPrograms, resolveLogo, main }
