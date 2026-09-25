const assert = require('node:assert/strict')
const { test } = require('node:test')
const { validateChannels, selectPrograms, resolveLogo } = require('./check_telemach')

test('selects programs across a UTC midnight boundary', () => {
  const hour = 3600000
  const now = Date.parse('2026-09-25T00:15:00Z')
  const programs = [
    { title: 'Next', start: now + hour, stop: now + 2 * hour },
    { title: 'Current', start: now - hour, stop: now + hour },
    { title: 'Previous', start: now - 2 * hour, stop: now - hour }
  ]
  const result = selectPrograms(programs, now)
  assert.deepEqual([result.previous?.title, result.current?.title, result.next?.title], ['Previous', 'Current', 'Next'])
})

test('shows neighbors when the guide has no current program', () => {
  const programs = [
    { title: 'Past', start: 0, stop: 100 },
    { title: 'Future', start: 300, stop: 400 }
  ]
  const result = selectPrograms(programs, 200)
  assert.deepEqual([result.previous?.title, result.current, result.next?.title], ['Past', null, 'Future'])
})

test('reads channel logos and keeps site IDs as strings', () => {
  assert.equal(resolveLogo({ images: [{ path: '/logo.png', type: 'LOGO' }] }), 'https://images-web.ug-be.cdn.united.cloud/logo.png')
  assert.deepEqual(validateChannels({ channels: [{ name: '  N1  ', site_id: '00199', country: 'ba' }] }), [
    { name: 'N1', site_id: '00199', country: 'ba' }
  ])
})
