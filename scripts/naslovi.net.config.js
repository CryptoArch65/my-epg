// Eurosport Serbia schedules on Naslovi.net. Each TV day runs into the
// early hours of the next calendar day, so advance the date at midnight.
const cheerio = require('cheerio')
const dayjs = require('dayjs')
const utc = require('dayjs/plugin/utc')
const timezone = require('dayjs/plugin/timezone')
dayjs.extend(utc)
dayjs.extend(timezone)

const TZ = 'Europe/Belgrade'
const SITE_IDS = new Set(['eurosport', 'eurosport-2', 'k1'])

module.exports = {
  site: 'naslovi.net',
  tz: TZ,
  lang: 'sr',
  days: 2,
  url({ channel, date }) {
    if (!SITE_IDS.has(channel.site_id)) throw new Error('Unknown Naslovi.net channel')
    return `https://naslovi.net/tv-program/${channel.site_id}/${date.format('YYYY-MM-DD')}`
  },
  parser({ content, date }) {
    const $ = cheerio.load(content)
    const rows = $('div.tvrow')
    const programs = []
    let dayOffset = 0
    let previous

    rows.each((_, row) => {
      const time = $(row).find('.time').first().text().trim()
      const title = $(row).find('.title').first().text().trim()
      if (!/^\d{1,2}:\d{2}$/.test(time) || !title || title.toLowerCase() === 'no information') return
      const [hour, minute] = time.split(':').map(Number)
      if (hour > 23 || minute > 59) return
      if (previous && hour * 60 + minute < previous) dayOffset += 1
      previous = hour * 60 + minute
      const startDate = date.add(dayOffset, 'day').format('YYYY-MM-DD')
      const start = dayjs.tz(`${startDate} ${time}`, 'YYYY-MM-DD HH:mm', TZ)
      const description = $(row).find('.descr').first().text().trim()
      const category = $(row).find('.category').first().text().trim()
      programs.push({ title, description, category, start })
    })

    for (let i = 0; i < programs.length; i++) {
      const next = programs[i + 1]?.start
      programs[i].stop = next && next.isAfter(programs[i].start)
        ? next
        : programs[i].start.add(1, 'hour')
    }
    return programs
  }
}
