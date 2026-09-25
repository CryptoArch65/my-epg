#!/usr/bin/env node
const fs = require('node:fs/promises')
const path = require('node:path')
const root = path.resolve(__dirname, '..')

async function main() {
  const configPath = path.join(root, 'config', 'epg-check.json')
  const config = JSON.parse(await fs.readFile(configPath, 'utf8'))
  if (config.source === 'mtel') {
    await require('./check_mtel').main(config)
  } else if (config.source === 'telemach') {
    await require('./check_telemach').main({ configPath, reportBase: 'epg-check' })
  } else {
    throw new Error('source mora biti "mtel" ili "telemach"; svaki drugi izvor zahtijeva svoj EPG adapter')
  }
}

if (require.main === module) main().catch(error => { console.error(error.message); process.exitCode = 1 })
module.exports = { main }
