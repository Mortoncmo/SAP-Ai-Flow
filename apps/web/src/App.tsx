import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
  Node,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  getViewportForBounds,
} from '@xyflow/react'
import { toPng } from 'html-to-image'
import {
  Bot,
  FileJson,
  FilePlus2,
  ImageDown,
  LayoutDashboard,
  LoaderCircle,
  PanelRight,
  Redo2,
  Send,
  Undo2,
  Upload,
} from 'lucide-react'
import { ApiError, modifyFlowchart } from './api/client'
import { Inspector } from './components/Inspector'
import { createEmptyGraph, createId } from './data'
import { BusinessNode, BusinessNodeData, BusinessNodeModel } from './flow/BusinessNode'
import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from './flow/layout'
import { useFlowStore } from './stores/flowStore'
import type { GraphDocument } from './types'

const nodeTypes = { business: BusinessNode }

function FlowWorkspace() {
  const graph = useFlowStore((state) => state.graph)
  const past = useFlowStore((state) => state.past)
  const future = useFlowStore((state) => state.future)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const undo = useFlowStore((state) => state.undo)
  const redo = useFlowStore((state) => state.redo)
  const reset = useFlowStore((state) => state.reset)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [instruction, setInstruction] = useState('在信用检查后增加经理审批')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('本地规则引擎已就绪')
  const [error, setError] = useState('')
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const abortRef = useRef<AbortController | null>(null)
  const importRef = useRef<HTMLInputElement>(null)
  const { fitView, getNodes, getNodesBounds } = useReactFlow()

  const fitCanvas = useCallback(() => {
    window.setTimeout(() => {
      void fitView({ padding: 0.18, maxZoom: 1.15, duration: 280 })
    }, 40)
  }, [fitView])

  useEffect(() => {
    const handleResize = () => fitCanvas()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [fitCanvas])

  const visualNodes = useMemo<BusinessNodeModel[]>(
    () =>
      graph.nodes.map((node) => ({
        id: node.id,
        type: 'business',
        position: graph.layout[node.id] ?? { x: 0, y: 0 },
        data: {
          label: node.label,
          description: node.description,
          nodeType: node.type,
          direction: graph.direction,
        } satisfies BusinessNodeData,
        selected: node.id === selectedNodeId,
      })),
    [graph, selectedNodeId],
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<BusinessNodeModel>(visualNodes)

  useEffect(() => setNodes(visualNodes), [setNodes, visualNodes])

  const visualEdges = useMemo<Edge[]>(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label ?? undefined,
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: { stroke: '#68736d', strokeWidth: 1.7 },
        labelStyle: { fill: '#3f4944', fontSize: 12, fontWeight: 600 },
        labelBgStyle: { fill: '#f7f7f4', fillOpacity: 0.94 },
      })),
    [graph.edges],
  )

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const command = instruction.trim()
    if (!command || pending) return
    setPending(true)
    setError('')
    setMessage('正在分析流程变更')
    const controller = new AbortController()
    abortRef.current = controller
    const baseVersion = graph.version
    try {
      const response = await modifyFlowchart(graph, command, controller.signal)
      if (useFlowStore.getState().graph.version !== baseVersion) {
        throw new ApiError('画布已发生变化，本次响应未应用。', 'STALE_RESPONSE')
      }
      commitGraph(layoutGraph(response.graph))
      fitCanvas()
      setInstruction('')
      setMessage(
        `${response.applied_patch.change_summary} · ${response.metrics.latency_ms} ms · ${response.metrics.provider}`,
      )
      if (response.warnings.length) setError(response.warnings.join(' '))
    } catch (caught) {
      if ((caught as Error).name === 'AbortError') {
        setMessage('已取消本次修改')
      } else {
        setError(caught instanceof Error ? caught.message : '流程修改失败')
        setMessage('当前画布未变更')
      }
    } finally {
      setPending(false)
      abortRef.current = null
    }
  }

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) return
      commitGraph({
        ...graph,
        version: graph.version + 1,
        edges: [
          ...graph.edges,
          {
            id: createId('edge'),
            source: connection.source,
            target: connection.target,
            label: null,
          },
        ],
      })
    },
    [commitGraph, graph],
  )

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const parsed = JSON.parse(await file.text()) as GraphDocument
      if (parsed.schema_version !== '1.0' || !Array.isArray(parsed.nodes) || !Array.isArray(parsed.edges)) {
        throw new Error('文件不是有效的 SAP AI Flow JSON。')
      }
      commitGraph(Object.keys(parsed.layout ?? {}).length ? parsed : layoutGraph(parsed))
      fitCanvas()
      setMessage(`已导入 ${file.name}`)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '导入失败')
    }
  }

  const exportJson = () => {
    downloadBlob(
      new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json;charset=utf-8' }),
      `${safeName(graph.title)}.json`,
    )
    setMessage('JSON 已导出')
  }

  const exportPng = async () => {
    const viewport = document.querySelector('.react-flow__viewport') as HTMLElement | null
    if (!viewport || getNodes().length === 0) return
    setMessage('正在生成 PNG')
    try {
      const bounds = getNodesBounds(getNodes())
      const width = Math.max(1200, Math.ceil(bounds.width + 160))
      const height = Math.max(760, Math.ceil(bounds.height + 160))
      const transform = getViewportForBounds(bounds, width, height, 0.5, 2, 0.12)
      const dataUrl = await toPng(viewport, {
        backgroundColor: '#f7f7f4',
        width,
        height,
        style: {
          width: `${width}px`,
          height: `${height}px`,
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`,
        },
        pixelRatio: 2,
      })
      const anchor = document.createElement('a')
      anchor.href = dataUrl
      anchor.download = `${safeName(graph.title)}.png`
      anchor.click()
      setMessage('PNG 已导出')
    } catch {
      setError('PNG 导出失败，请重试。')
    }
  }

  const toggleDirection = () => {
    const direction = graph.direction === 'TB' ? 'LR' : 'TB'
    commitGraph(layoutGraph({ ...graph, version: graph.version + 1, direction }))
    fitCanvas()
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">
          <Bot size={20} />
        </div>
        <div className="brand-copy">
          <strong>SAP AI Flow</strong>
          <span>{graph.title}</span>
        </div>
        <div className="header-status">
          <span className={pending ? 'status-dot is-pending' : 'status-dot'} />
          {pending ? '处理中' : '已就绪'}
        </div>
      </header>

      <nav className="toolbar" aria-label="流程工具栏">
        <div className="toolbar__group">
          <button
            className="icon-button"
            title="新建流程"
            aria-label="新建流程"
            onClick={() => {
              if (graph.nodes.length > 0 && !window.confirm('新建流程将清空当前画布，是否继续？')) return
              reset(createEmptyGraph())
              setSelectedNodeId(null)
              setMessage('已新建空白流程')
              fitCanvas()
            }}
          >
            <FilePlus2 size={18} />
          </button>
          <button
            className="icon-button"
            title="导入 JSON"
            aria-label="导入 JSON"
            onClick={() => importRef.current?.click()}
          >
            <Upload size={18} />
          </button>
          <input ref={importRef} type="file" accept="application/json,.json" hidden onChange={handleImport} />
          <button className="icon-button" title="导出 JSON" aria-label="导出 JSON" onClick={exportJson}>
            <FileJson size={18} />
          </button>
          <button className="icon-button" title="导出 PNG" aria-label="导出 PNG" onClick={exportPng}>
            <ImageDown size={18} />
          </button>
        </div>
        <span className="toolbar__separator" />
        <div className="toolbar__group">
          <button className="icon-button" title="撤销" aria-label="撤销" disabled={!past.length} onClick={undo}>
            <Undo2 size={18} />
          </button>
          <button className="icon-button" title="重做" aria-label="重做" disabled={!future.length} onClick={redo}>
            <Redo2 size={18} />
          </button>
          <button
            className="icon-button"
            title="自动布局"
            aria-label="自动布局"
            onClick={() => {
              commitGraph(layoutGraph({ ...graph, version: graph.version + 1 }))
              fitCanvas()
            }}
          >
            <LayoutDashboard size={18} />
          </button>
        </div>
        <span className="toolbar__separator" />
        <div className="segmented" aria-label="布局方向">
          <button className={graph.direction === 'TB' ? 'is-active' : ''} onClick={toggleDirection}>
            纵向
          </button>
          <button className={graph.direction === 'LR' ? 'is-active' : ''} onClick={toggleDirection}>
            横向
          </button>
        </div>
        <button
          className="icon-button toolbar__inspector-toggle"
          title="属性面板"
          aria-label="属性面板"
          onClick={() => setInspectorOpen((value) => !value)}
        >
          <PanelRight size={18} />
        </button>
      </nav>

      <main className={`workspace${inspectorOpen ? '' : ' inspector-closed'}`}>
        <section className="canvas-region" aria-label="流程图画布">
          <ReactFlow<BusinessNodeModel>
            nodes={nodes}
            edges={visualEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onConnect={handleConnect}
            onNodeClick={(_, node) => setSelectedNodeId(node.id)}
            onPaneClick={() => setSelectedNodeId(null)}
            onNodeDragStop={(_, node) =>
              commitGraph({
                ...graph,
                version: graph.version + 1,
                layout: { ...graph.layout, [node.id]: node.position },
              })
            }
            onNodesDelete={(deleted: Node[]) => {
              const ids = new Set(deleted.map((node) => node.id))
              commitGraph({
                ...graph,
                version: graph.version + 1,
                nodes: graph.nodes.filter((node) => !ids.has(node.id)),
                edges: graph.edges.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)),
                layout: Object.fromEntries(Object.entries(graph.layout).filter(([id]) => !ids.has(id))),
              })
              setSelectedNodeId(null)
            }}
            onEdgesDelete={(deleted: Edge[]) => {
              const ids = new Set(deleted.map((edge) => edge.id))
              commitGraph({
                ...graph,
                version: graph.version + 1,
                edges: graph.edges.filter((edge) => !ids.has(edge.id)),
              })
            }}
            fitView
            fitViewOptions={{ padding: 0.18, maxZoom: 1.15 }}
            minZoom={0.25}
            maxZoom={1.8}
            deleteKeyCode={['Backspace', 'Delete']}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#cbd0cb" />
            <Controls position="bottom-left" showInteractive={false} />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              nodeColor={(node) => nodeColor((node.data as BusinessNodeData).nodeType)}
              maskColor="rgba(247, 247, 244, 0.78)"
            />
            {graph.nodes.length === 0 && (
              <div className="empty-canvas">
                <Bot size={28} />
                <strong>空白流程</strong>
              </div>
            )}
          </ReactFlow>
        </section>
        {inspectorOpen && (
          <Inspector selectedNodeId={selectedNodeId} onClearSelection={() => setSelectedNodeId(null)} />
        )}
      </main>

      <footer className="command-dock">
        <div className="command-dock__status" role="status">
          <span>{message}</span>
          {error && <span className="command-dock__error">{error}</span>}
        </div>
        <form onSubmit={handleSubmit}>
          <Bot size={20} aria-hidden="true" />
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            rows={1}
            maxLength={4000}
            placeholder="输入流程修改指令"
            aria-label="流程修改指令"
          />
          {pending ? (
            <button
              type="button"
              className="command-button cancel"
              onClick={() => abortRef.current?.abort()}
            >
              <LoaderCircle size={18} className="spin" />
              <span>取消</span>
            </button>
          ) : (
            <button type="submit" className="command-button" disabled={!instruction.trim()}>
              <Send size={18} />
              <span>执行</span>
            </button>
          )}
        </form>
      </footer>
    </div>
  )
}

export default function App() {
  return (
    <ReactFlowProvider>
      <FlowWorkspace />
    </ReactFlowProvider>
  )
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function safeName(name: string): string {
  return name.replace(/[\\/:*?"<>|]/g, '-').trim() || 'flowchart'
}

function nodeColor(type: string): string {
  const colors: Record<string, string> = {
    start: '#2d7a5e',
    end: '#ad4c4c',
    task: '#3e6f98',
    decision: '#c58b2c',
    subprocess: '#745d91',
  }
  return colors[type] ?? '#68736d'
}
