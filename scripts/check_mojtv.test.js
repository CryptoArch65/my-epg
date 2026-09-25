const test = require('node:test')
const assert = require('node:assert/strict')
const { validateChannels, dateForOffset, xmltvTime } = require('./check_mojtv')
const { selectPrograms } = require('./check_telemach')

test('MojTV kanal ima proizvoljan naziv i brojčani site_id', () => {
  assert.deepEqual(validateChannels({ channels: [{ name: ' Moj B92 ', site_id: '31' }] }),
    [{ name: 'Moj B92', site_id: '31' }])
  assert.throws(() => validateChannels({ channels: [{ name: 'B92', site_id: '31/b92' }] }), /brojčani/)
  assert.throws(() => validateChannels({ channels: [
    { name: 'B92', site_id: '31' }, { name: 'B92 HD', site_id: '31' }
  ] }), /Ponovljeni/)
})

test('XMLTV sat i pomak daju tačno UTC vrijeme', () => {
  assert.equal(xmltvTime('20260925134500 +0200'), Date.parse('2026-09-25T11:45:00Z'))
  assert.equal(xmltvTime('20261225134500 +0100'), Date.parse('2026-12-25T12:45:00Z'))
  assert.ok(Number.isNaN(xmltvTime('neispravno')))
})

test('prethodna, trenutna i sljedeća emisija prelaze granicu dana', () => {
  const programs = [
    { title: 'Prethodna', start: xmltvTime('20260925234500 +0200'), stop: xmltvTime('20260926000000 +0200') },
    { title: 'Trenutna', start: xmltvTime('20260926000000 +0200'), stop: xmltvTime('20260926003000 +0200') },
    { title: 'Sljedeća', start: xmltvTime('20260926003000 +0200'), stop: xmltvTime('20260926010000 +0200') }
  ]
  const selected = selectPrograms(programs, xmltvTime('20260926000500 +0200'))
  assert.equal(selected.previous.title, 'Prethodna')
  assert.equal(selected.current.title, 'Trenutna')
  assert.equal(selected.next.title, 'Sljedeća')
  assert.equal(dateForOffset(Date.parse('2026-09-25T22:05:00Z'), -1), '25.9.2026.')
  assert.equal(dateForOffset(Date.parse('2026-09-25T22:05:00Z'), 0), '26.9.2026.')
})
