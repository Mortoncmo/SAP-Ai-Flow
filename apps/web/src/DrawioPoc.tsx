import { ChangeEvent, useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, Download, ExternalLink, FileUp, LoaderCircle, RefreshCw, Save } from 'lucide-react'
import { getDrawioRevision, saveDrawioRevision } from './api/client'
import { drawioXmlToGraph, graphToDrawioXml } from './drawio/adapter'
import type { GraphDocument } from './types'

const DRAWIO_ORIGIN = 'https://embed.diagrams.net'
const DRAWIO_EDITOR_URL = `${DRAWIO_ORIGIN}/?embed=1&proto=json&spin=1&ui=atlas&libraries=1`
const DRAWIO_SAMPLE_URL = '/poc/drawio-sample.drawio'
const DRAWIO_SAMPLE_NAME = '设备租赁采购流程.drawio'

type DrawioMessage = {
  event?: string
  format?: string
  xml?: string
  data?: string
  error?: string
}

function parseMessage(data: unknown): DrawioMessage | null {
  if (typeof data !== 'string') return null
  try {
    const parsed: unknown = JSON.parse(data)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed as DrawioMessage
  } catch {
    return null
  }
}

function downloadBlob(content: BlobPart, filename: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

async function downloadExport(data: string, filename: string, fallbackType: string): Promise<void> {
  if (data.startsWith('data:')) {
    const response = await fetch(data)
    downloadBlob(await response.blob(), filename, response.headers.get('Content-Type') ?? fallbackType)
    return
  }
  downloadBlob(data, filename, fallbackType)
}

export function DrawioPoc() {
  const query = new URLSearchParams(window.location.search)
  const processId = query.get('processId')
  const initialRevision = Number(query.get('revision') || '0')
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const xmlRef = useRef('')
  const graphRef = useRef<GraphDocument | null>(null)
  const revisionRef = useRef(initialRevision)
  const hashRef = useRef<string | null>(null)
  const editorReadyRef = useRef(false)
  const [editorReady, setEditorReady] = useState(false)
  const [sampleLoading, setSampleLoading] = useState(true)
  const [status, setStatus] = useState('正在加载示例流程图')
  const [error, setError] = useState('')

  const send = useCallback((message: Record<string, unknown>) => {
    iframeRef.current?.contentWindow?.postMessage(JSON.stringify(message), DRAWIO_ORIGIN)
  }, [])

  const loadXml = useCallback((xml: string, sourceName: string) => {
    xmlRef.current = xml
    setError('')
    if (!editorReadyRef.current) {
      setStatus(`已读取 ${sourceName}，等待 Draw.io 编辑器就绪`)
      return
    }
    send({ action: 'load', xml, autosave: 1 })
    setStatus(`已加载 ${sourceName}`)
  }, [send])

  const loadSample = useCallback(async () => {
    setSampleLoading(true)
    setError('')
    try {
      if (processId) {
        const revision = await getDrawioRevision(processId, revisionRef.current)
        graphRef.current = revision.graph
        hashRef.current = revision.xml_sha256
        loadXml(revision.xml || graphToDrawioXml(revision.graph), `流程修订 r${revision.revision_no}`)
        return
      }
      const response = await fetch(DRAWIO_SAMPLE_URL, { cache: 'no-store' })
      if (!response.ok) throw new Error(`示例流程图读取失败（${response.status}）`)
      loadXml(await response.text(), DRAWIO_SAMPLE_NAME)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '示例流程图读取失败')
      setStatus('无法读取示例流程图')
    } finally {
      setSampleLoading(false)
    }
  }, [loadXml, processId])

  useEffect(() => {
    void loadSample()
  }, [loadSample])

  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.origin !== DRAWIO_ORIGIN) return
      const message = parseMessage(event.data)
      if (!message) return

      if (message.event === 'init') {
        editorReadyRef.current = true
        setEditorReady(true)
        if (xmlRef.current) {
          send({ action: 'load', xml: xmlRef.current, autosave: 1 })
          setStatus('Draw.io 编辑器已就绪')
        }
        return
      }
      if (message.event === 'save' && message.xml) {
        xmlRef.current = message.xml
        downloadBlob(message.xml, DRAWIO_SAMPLE_NAME, 'application/xml;charset=utf-8')
        setStatus('已保存当前 Draw.io 文件')
        return
      }
      if (message.event === 'export' && message.format === 'xml' && message.xml) {
        xmlRef.current = message.xml
        if (processId && graphRef.current) {
          void persistDrawio(message.xml)
        } else {
          downloadBlob(message.xml, DRAWIO_SAMPLE_NAME, 'application/xml;charset=utf-8')
          setStatus('已保存当前 Draw.io 文件')
        }
        return
      }
      if (message.event === 'export' && message.data) {
        void downloadExport(message.data, '设备租赁采购流程.svg', 'image/svg+xml')
          .then(() => setStatus('已导出 SVG'))
          .catch(() => setError('SVG 导出失败，请使用编辑器内置导出菜单重试'))
        return
      }
      if (message.event === 'exit') {
        window.location.assign('/')
        return
      }
      if (message.event === 'error') setError(message.error || 'Draw.io 操作失败')
    }

    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [send])

  const persistDrawio = async (xml: string) => {
    if (!processId || !graphRef.current) return
    try {
      const projected = drawioXmlToGraph(xml)
      projected.graph_id = graphRef.current.graph_id
      projected.module = graphRef.current.module
      projected.process_scope = graphRef.current.process_scope
      projected.sap_context = graphRef.current.sap_context
      projected.version = revisionRef.current + 1
      const digest = await sha256Hex(xml)
      const saved = await saveDrawioRevision(
        processId,
        revisionRef.current,
        hashRef.current,
        xml,
        digest,
        projected,
      )
      graphRef.current = saved.graph
      revisionRef.current = saved.revision_no
      hashRef.current = saved.xml_sha256
      setStatus(`已保存到流程修订 r${saved.revision_no}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Draw.io 修订保存失败')
      setStatus('当前 Draw.io 文件未保存到项目')
    }
  }

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const xml = await file.text()
      if (!xml.includes('<mxfile') || !xml.includes('<mxGraphModel')) {
        throw new Error('文件不是有效的 Draw.io 流程图')
      }
      loadXml(xml, file.name)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Draw.io 文件读取失败')
    }
  }

  const save = () => {
    if (!editorReady) return
    setError('')
    setStatus('正在准备 Draw.io 文件')
    send({ action: 'export', format: 'xml' })
  }

  const exportSvg = () => {
    if (!editorReady) return
    setError('')
    setStatus('正在导出 SVG')
    send({ action: 'export', format: 'svg', spinKey: 'drawio-poc-export' })
  }

  return (
    <div className="drawio-poc-shell">
      <header className="drawio-poc-header">
        <a className="drawio-poc-back" href="/" title="返回 SAP AI Flow" aria-label="返回 SAP AI Flow">
          <ArrowLeft size={18} />
        </a>
        <div className="drawio-poc-heading">
          <strong>Draw.io 流程图 POC</strong>
          <span>现有 SAP 业务流程图编辑验证</span>
        </div>
        <span className={`drawio-poc-dot${editorReady ? ' is-ready' : ''}`} aria-hidden="true" />
        <span className="drawio-poc-state">{editorReady ? '编辑器已连接' : '连接中'}</span>
        <a
          className="drawio-poc-open"
          href={DRAWIO_EDITOR_URL}
          target="_blank"
          rel="noreferrer"
          title="在新窗口打开 Draw.io"
        >
          <ExternalLink size={16} />
          <span>新窗口</span>
        </a>
      </header>

      <nav className="drawio-poc-toolbar" aria-label="Draw.io POC 工具栏">
        <div className="drawio-poc-actions">
          <button type="button" className="icon-button" onClick={() => void loadSample()} disabled={sampleLoading} title="重新加载示例">
            {sampleLoading ? <LoaderCircle size={17} className="spin" /> : <RefreshCw size={17} />}
            <span>示例</span>
          </button>
          <label className="icon-button" title="导入 Draw.io 文件">
            <FileUp size={17} />
            <span>导入</span>
            <input type="file" accept=".drawio,.xml,application/xml" hidden onChange={(event) => void handleImport(event)} />
          </label>
          <button type="button" className="icon-button" onClick={save} disabled={!editorReady} title="保存 Draw.io 文件">
            <Save size={17} />
            <span>保存</span>
          </button>
          <button type="button" className="icon-button" onClick={exportSvg} disabled={!editorReady} title="导出 SVG">
            <Download size={17} />
            <span>SVG</span>
          </button>
        </div>
        <div className="drawio-poc-hint">
          <span>{status}</span>
          {error && <span className="drawio-poc-error" role="alert">{error}</span>}
        </div>
      </nav>

      <main className="drawio-poc-frame" aria-label="Draw.io 编辑器">
        <iframe
          ref={iframeRef}
          title="Draw.io 流程图编辑器"
          src={DRAWIO_EDITOR_URL}
          allow="clipboard-read; clipboard-write"
          referrerPolicy="no-referrer"
        />
      </main>
    </div>
  )
}

async function sha256Hex(value: string): Promise<string> {
  const bytes = new TextEncoder().encode(value)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
}
