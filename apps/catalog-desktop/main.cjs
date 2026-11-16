const { app, BrowserWindow, dialog, shell } = require('electron')
const { spawn } = require('node:child_process')
const net = require('node:net')
const path = require('node:path')
const fs = require('node:fs')

let backend = null
let mainWindow = null
let quitting = false
let backendError = ''
let started = false

function stateDirectory() {
  const override = process.env.MAKERSFRIDGE_DESKTOP_STATE || process.env.MAKERS_SUPPLY_DESKTOP_STATE
  if (override) return path.resolve(override)
  const base = app.getPath('appData')
  const current = path.join(base, 'makersfridge')
  if (fs.existsSync(current)) return current
  for (const name of ["Maker's Supply Catalog", 'makers-supply-catalog-desktop', 'makers-supply-catalog']) {
    const legacy = path.join(base, name)
    if (fs.existsSync(legacy)) return legacy
  }
  return current
}

app.setPath('userData', stateDirectory())

function dataDirectory() {
  const override = process.env.MAKERSFRIDGE_DESKTOP_DATA || process.env.MAKERS_SUPPLY_DESKTOP_DATA
  if (override) {
    return path.resolve(override)
  }
  if (process.platform === 'darwin') {
    return path.resolve(path.dirname(process.execPath), '../../..')
  }
  return path.dirname(process.execPath)
}

function backendExecutable() {
  const filename = process.platform === 'win32'
    ? 'makersfridge-backend.exe'
    : 'makersfridge-backend'
  return path.join(process.resourcesPath, 'backend', filename)
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : null
      server.close(() => port ? resolve(port) : reject(new Error('No local port available')))
    })
  })
}

async function waitForBackend(url) {
  for (let attempt = 0; attempt < 1200; attempt += 1) {
    if (backend?.exitCode !== null) {
      throw new Error(`Catalog service exited with code ${backend.exitCode}.\n${backendError}`)
    }
    try {
      const response = await fetch(`${url}/healthz`)
      if (response.ok) return
    } catch {
      // The sidecar is still starting.
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Catalog service did not become ready')
}

function openExternalLinks(window, localOrigin) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    const target = new URL(url)
    if (target.origin !== localOrigin && ['http:', 'https:'].includes(target.protocol)) {
      void shell.openExternal(url)
    }
    return { action: 'deny' }
  })
  window.webContents.on('will-navigate', (event, url) => {
    const target = new URL(url)
    if (target.origin !== localOrigin) {
      event.preventDefault()
      if (['http:', 'https:'].includes(target.protocol)) void shell.openExternal(url)
    }
  })
}

async function loadInitialPage(window, url) {
  try {
    await window.loadURL(url)
  } catch (error) {
    // The window can be used before every initial resource finishes loading.
    // A local link can therefore cancel this first navigation without a startup failure.
    if (error?.code !== 'ERR_ABORTED' || window.isDestroyed()) throw error
  }
}

async function startApplication() {
  const port = await reservePort()
  const url = `http://127.0.0.1:${port}`
  backend = spawn(
    backendExecutable(),
    [
      '--port', String(port),
      '--data-dir', dataDirectory(),
      '--state-dir', app.getPath('userData')
    ],
    { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true }
  )
  const spawnFailure = new Promise((resolve, reject) => {
    backend.once('error', reject)
  })
  backend.stdout.on('data', chunk => console.log(`[catalog] ${chunk.toString().trimEnd()}`))
  backend.stderr.on('data', chunk => {
    backendError = (backendError + chunk.toString()).slice(-8192)
    console.error(`[catalog] ${chunk.toString().trimEnd()}`)
  })
  backend.once('exit', code => {
    if (!quitting && started) {
      dialog.showErrorBox('Maker\'s Fridge stopped', `The local service exited (${code}).`)
      app.quit()
    }
  })
  await Promise.race([waitForBackend(url), spawnFailure])

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 960,
    minHeight: 640,
    show: false,
    autoHideMenuBar: true,
    backgroundColor: '#f4f1ea',
    title: "Maker's Fridge",
    webPreferences: {
      contextIsolation: true,
      devTools: false,
      nodeIntegration: false,
      sandbox: true
    }
  })
  openExternalLinks(mainWindow, new URL(url).origin)
  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.once('closed', () => {
    mainWindow = null
    app.quit()
  })
  await loadInitialPage(mainWindow, url)
  started = true
}

const singleInstance = app.requestSingleInstanceLock()
if (!singleInstance) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
  app.whenReady().then(startApplication).catch(error => {
    console.error('[catalog startup]', error)
    if (!quitting) dialog.showErrorBox("Maker's Fridge could not start", String(error))
    app.quit()
  })
}

app.on('before-quit', () => {
  quitting = true
  if (backend && backend.exitCode === null) backend.kill()
})

app.on('window-all-closed', () => app.quit())
