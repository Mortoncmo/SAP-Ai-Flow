import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

const repoRoot = path.resolve(fileURLToPath(new URL('.', import.meta.url)), '../..')
const drawioSource = path.join(repoRoot, '设备租赁采购流程方案', '设备租赁采购流程.drawio')
const drawioPublicPath = '/poc/drawio-sample.drawio'

export const drawioPocPaths = { drawioSource, drawioPublicPath }

function drawioPocSource(): Plugin {
  const serveSource = (
    req: { method?: string; url?: string },
    res: {
      statusCode: number
      setHeader: (name: string, value: string) => void
      end: (content: Buffer) => void
    },
    next: () => void,
  ) => {
    const requestPath = req.url?.split('?')[0]
    if (req.method !== 'GET' || requestPath !== drawioPublicPath) {
      next()
      return
    }
    try {
      res.statusCode = 200
      res.setHeader('Content-Type', 'application/xml; charset=utf-8')
      res.setHeader('Cache-Control', 'no-store')
      res.end(fs.readFileSync(drawioSource))
    } catch {
      res.statusCode = 404
      res.end(Buffer.from('Draw.io source not found'))
    }
  }

  return {
    name: 'drawio-poc-source',
    configureServer(server) {
      server.middlewares.use(serveSource)
    },
    configurePreviewServer(server) {
      server.middlewares.use(serveSource)
    },
    generateBundle() {
      if (fs.existsSync(drawioSource)) {
        this.emitFile({
          type: 'asset',
          fileName: 'poc/drawio-sample.drawio',
          source: fs.readFileSync(drawioSource),
        })
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), drawioPocSource()],
  envDir: '../../',
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
  },
})
