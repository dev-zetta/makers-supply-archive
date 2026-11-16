const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(path.join(__dirname, '../main.cjs'), 'utf8')
const loadInitialPage = vm.runInNewContext(source + '\nloadInitialPage', {
  require: name => name === 'electron'
    ? { app: {
        getPath: () => '/tmp/makersfridge-startup-test', setPath() {},
        requestSingleInstanceLock: () => false, quit() {}, on() {}
      } }
    : require(name),
  process: { env: {} },
  console
})

test('early navigation can cancel the initial load without a fatal startup error', async () => {
  const error = Object.assign(new Error('navigation superseded'), { code: 'ERR_ABORTED' })
  await loadInitialPage({
    loadURL: () => Promise.reject(error),
    isDestroyed: () => false
  }, 'http://127.0.0.1:8000/')
})

test('genuine initial page failures remain fatal', async () => {
  const error = Object.assign(new Error('service unavailable'), { code: 'ERR_CONNECTION_REFUSED' })
  await assert.rejects(loadInitialPage({
    loadURL: () => Promise.reject(error),
    isDestroyed: () => false
  }, 'http://127.0.0.1:8000/'), candidate => candidate === error)
})

test('an aborted load in a destroyed window is reported to the shutdown handler', async () => {
  const error = Object.assign(new Error('window closed'), { code: 'ERR_ABORTED' })
  await assert.rejects(loadInitialPage({
    loadURL: () => Promise.reject(error),
    isDestroyed: () => true
  }, 'http://127.0.0.1:8000/'), candidate => candidate === error)
})

test('renamed desktop app reuses its old profile and honors explicit overrides', () => {
  const existing = new Set([path.join('/profiles', "Maker's Supply Catalog")])
  const env = {}
  let selected
  const choose = vm.runInNewContext(source + '\nstateDirectory', {
    require: name => {
      if (name === 'electron') return { app: {
        getPath: () => '/profiles', setPath: (_, value) => { selected = value },
        requestSingleInstanceLock: () => false, quit() {}, on() {}
      } }
      if (name === 'node:fs') return { existsSync: value => existing.has(value) }
      return require(name)
    },
    process: { env }, console
  })
  assert.equal(selected, path.join('/profiles', "Maker's Supply Catalog"))
  existing.add(path.join('/profiles', 'makersfridge'))
  assert.equal(choose(), path.join('/profiles', 'makersfridge'))
  env.MAKERS_SUPPLY_DESKTOP_STATE = '/legacy-override'
  assert.equal(choose(), path.resolve('/legacy-override'))
  env.MAKERSFRIDGE_DESKTOP_STATE = '/new-override'
  assert.equal(choose(), path.resolve('/new-override'))
})
