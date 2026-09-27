// Read the schedules embedded in the official Serbian Arena Sport TV page.
// The upstream scraper expects rendered slider HTML; the current site leaves
// off-screen sliders empty and keeps their complete data in TV_SCHEMES instead.
const dayjs = require('dayjs')
const utc = require('dayjs/plugin/utc')
const timezone = require('dayjs/plugin/timezone')
dayjs.extend(utc)
dayjs.extend(timezone)

const TIMEZONE = 'Europe/Belgrade'
const SITE = 'tvarenasport.com'

function channelName(siteId) {
  const premium = /^a+([1-5])p$/.exec(siteId)
  if (premium) return `Arena Premium ${premium[1]}`
  const regular = /^0*(\d+)$/.exec(siteId)
  if (regular) return `Arena Sport ${regular[1]}`
  if (siteId === 'a-tenis') return 'Arena Tenis'
  if (siteId === '1x2') return 'Arena 1X2'
  return null
}

module.exports = {
  site: SITE,
  tz: TIMEZONE,
  lang: 'sr',
  days: 2,
  url: 'https://www.tvarenasport.com/tv-scheme',
  parser({ content, channel, date }) {
    const match = content.match(/window\.TV_SCHEMES\s*=\s*(\{[^\r\n]*\})\s*;/)
    if (!match) return []
    let schedules
    try {
      schedules = JSON.parse(match[1])
    } catch {
      return []
    }
    const name = channelName(channel.site_id)
    const day = date.format('YYYY-MM-DD')
    const entries = schedules[name]?.days?.[day]?.emisije
    if (!Array.isArray(entries)) return []

    const programs = entries
      .filter(item => /^\d{2}:\d{2}$/.test(item.time) && item.content)
      .map(item => ({
        title: [item.category, item.content].filter(Boolean).join(': '),
        description: item.description || undefined,
        category: item.sport || undefined,
        start: dayjs.tz(`${day} ${item.time}`, 'YYYY-MM-DD HH:mm', TIMEZONE)
      }))
    for (let i = 0; i < programs.length; i++) {
      const next = programs[i + 1]?.start
      programs[i].stop = next && next.isAfter(programs[i].start)
        ? next
        : dayjs.tz(`${day} 00:00`, 'YYYY-MM-DD HH:mm', TIMEZONE).add(1, 'day')
    }
    return programs
  }
}
