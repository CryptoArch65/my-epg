const assert = require('node:assert/strict')
const { test } = require('node:test')
const { validateChannels, normalisePrograms, resolveLogo } = require('./check_mtel')
const { selectPrograms } = require('./check_telemach')

test('accepts full IPTV site IDs and preserves the chosen channel names', () => {
  assert.deepEqual(validateChannels({ channels: [{ name: ' BHT 1 HD ', site_id: 'iptv#ch-15-bht' }] }), [
    { name: 'BHT 1 HD', site_id: 'iptv#ch-15-bht' }
  ])
  assert.throws(() => validateChannels({ channels: [{ name: 'BHT 1', site_id: 'ch-15-bht' }] }), /iptv#ch-/)
  assert.throws(() => validateChannels({ channels: [
    { name: 'A', site_id: 'iptv#ch-15-bht' }, { name: 'B', site_id: 'iptv#ch-15-bht' }
  ] }), /Ponovljeni/)
})

test('combines neighboring days and selects previous/current/next once', () => {
  const start = Date.parse('2026-09-25T21:30:00Z')
  const hour = 60 * 60 * 1000
  const source = [
    { title: 'Prije', start: new Date(start - hour), stop: new Date(start) },
    { title: 'Sada', start: new Date(start), stop: new Date(start + hour) },
    { title: 'Sada', start: new Date(start), stop: new Date(start + hour) },
    { title: 'Poslije', start: new Date(start + hour), stop: new Date(start + 2 * hour) }
  ]
  const programs = normalisePrograms(source)
  assert.equal(programs.length, 3)
  const selected = selectPrograms(programs, start + hour / 2)
  assert.deepEqual([selected.previous?.title, selected.current?.title, selected.next?.title], ['Prije', 'Sada', 'Poslije'])
})

test('uses a channel logo from the IPTV product', () => {
  assert.equal(resolveLogo({ picture: { url: '/medias/bht.png' } }), 'https://mtel.ba/medias/bht.png')
  assert.equal(resolveLogo({}), null)
})
