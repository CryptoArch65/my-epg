const assert = require('node:assert/strict')
const { test } = require('node:test')
const { validateChannels, normalisePrograms, resolveLogo } = require('./check_maxtv')
const { selectPrograms } = require('./check_telemach')

test('MAXtv keeps custom names and validates full station IDs', () => {
  assert.deepEqual(validateChannels({ channels: [
    { name: ' Moj HRT 1 HD ', site_id: '274913832105' }
  ] }), [{ name: 'Moj HRT 1 HD', site_id: '274913832105' }])
  assert.throws(() => validateChannels({ channels: [{ name: 'HRT', site_id: 'HRT1.hr' }] }), /brojčani/)
  assert.throws(() => validateChannels({ channels: [
    { name: 'HRT', site_id: '274913832105' }, { name: 'HRT HD', site_id: '274913832105' }
  ] }), /Ponovljeni/)
})

test('collects schedule windows across midnight without duplicate programmes', () => {
  const siteId = '274913832105'
  const responses = [
    { channels: { [siteId]: [
      { description: 'Prije', start_time: '2026-09-24T23:20:00Z', end_time: '2026-09-25T00:10:00Z' },
      { description: 'Trenutno', start_time: '2026-09-25T00:10:00Z', end_time: '2026-09-25T00:30:00Z' }
    ] } },
    { channels: { [siteId]: [
      { description: 'Trenutno', start_time: '2026-09-25T00:10:00Z', end_time: '2026-09-25T00:30:00Z' },
      { description: 'Sljedeće', start_time: '2026-09-25T00:30:00Z', end_time: '2026-09-25T01:20:00Z' }
    ] } }
  ]
  const programs = normalisePrograms(responses, siteId)
  assert.equal(programs.length, 3)
  const selected = selectPrograms(programs, Date.parse('2026-09-25T00:15:00Z'))
  assert.deepEqual([selected.previous?.title, selected.current?.title, selected.next?.title],
    ['Prije', 'Trenutno', 'Sljedeće'])
  assert.deepEqual(normalisePrograms(responses, '999'), [])
})

test('uses a MAXtv channel logo from the catalog', () => {
  assert.equal(resolveLogo({ channel_logo: 'https://tv-hr-prod.yo-digital.com/prod/images/logos/hrt.PNG' }),
    'https://tv-hr-prod.yo-digital.com/prod/images/logos/hrt.PNG')
  assert.equal(resolveLogo({ logo_image_url: '/prod/images/logos/hrt.PNG' }),
    'https://tv-hr-prod.yo-digital.com/prod/images/logos/hrt.PNG')
  assert.equal(resolveLogo({ logo_url: 'https://tv-hr-prod.yo-digital.com/rtl.png' }),
    'https://tv-hr-prod.yo-digital.com/rtl.png')
  assert.equal(resolveLogo({ logo_url: 'javascript:alert(1)' }), null)
})
