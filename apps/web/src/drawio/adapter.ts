import { emptySapMetadata, normalizeGraph } from '../data'
import type { FlowNode, GraphDocument, NodeType, SapMetadata, Swimlane } from '../types'

const META = {
  graphId: 'data-graph-id',
  version: 'data-version',
  module: 'data-module',
  processScope: 'data-process-scope',
  sapContext: 'data-sap-context',
  direction: 'data-direction',
  nodeType: 'data-node-type',
  description: 'data-description',
  icon: 'data-icon',
  sap: 'data-sap',
  laneColor: 'data-lane-color',
} as const

interface CellRecord {
  element: Element
  id: string
  parent: string | null
  source: string | null
  target: string | null
  value: string
  style: string
}

export function drawioXmlToGraph(xml: string): GraphDocument {
  const document = parseXml(xml)
  const model = document.querySelector('mxGraphModel')
  const diagram = document.querySelector('diagram')
  if (!model || !diagram) throw new Error('Draw.io 文件缺少 mxGraphModel')

  const cells = Array.from(model.querySelectorAll('mxCell')).map(readCell)
  const cellById = new Map(cells.map((cell) => [cell.id, cell]))
  const lanes = cells.filter(isLane).slice(0, 20).map(toLane)
  const laneIds = new Set(lanes.map((lane) => lane.id))
  const connectedIds = new Set(
    cells
      .filter((cell) => cell.source && cell.target)
      .flatMap((cell) => [cell.source as string, cell.target as string]),
  )
  const nodes = cells
    .filter((cell) => isSemanticNode(cell, laneIds, connectedIds))
    .slice(0, 500)
    .map((cell) => toNode(cell, laneIds))
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = cells
    .filter((cell) => cell.source && cell.target && nodeIds.has(cell.source) && nodeIds.has(cell.target))
    .slice(0, 1000)
    .map((cell) => ({
      id: cell.id,
      source: cell.source as string,
      target: cell.target as string,
      label: cleanLabel(cell.value) || null,
    }))
  const layout = Object.fromEntries(nodes.map((node) => {
    const cell = cellById.get(node.id)
    const lane = node.lane_id ? cellById.get(node.lane_id) : null
    const point = geometryPoint(cell?.element)
    const lanePoint = geometryPoint(lane?.element)
    return [node.id, {
      x: point.x + (node.lane_id ? lanePoint.x : 0),
      y: point.y + (node.lane_id ? lanePoint.y : 0),
    }]
  }))
  const root = model

  return normalizeGraph({
    schema_version: '2.0',
    graph_id: root.getAttribute(META.graphId) || diagram.getAttribute('id') || 'drawio_graph',
    version: numberAttribute(root, META.version, 0),
    title: cleanLabel(diagram.getAttribute('name') || '') || inferTitle(cells),
    module: root.getAttribute(META.module) || 'MM',
    process_scope: root.getAttribute(META.processScope) || 'P2P',
    sap_context: parseJson(root.getAttribute(META.sapContext), {}),
    direction: root.getAttribute(META.direction) === 'LR' ? 'LR' : inferDirection(nodes, layout),
    nodes,
    edges,
    lanes,
    layout,
  })
}

export function graphToDrawioXml(input: GraphDocument): string {
  const graph = normalizeGraph(input)
  const xmlDocument = window.document.implementation.createDocument('', 'mxfile')
  const mxfile = xmlDocument.documentElement
  mxfile.setAttribute('host', 'SAP AI Flow')
  mxfile.setAttribute('version', '26.0.0')
  const diagram = append(xmlDocument, mxfile, 'diagram', { id: graph.graph_id, name: graph.title })
  const model = append(xmlDocument, diagram, 'mxGraphModel', {
    grid: '1', gridSize: '10', guides: '1', connect: '1', arrows: '1', page: '1',
    pageWidth: '2200', pageHeight: '1220',
    [META.graphId]: graph.graph_id,
    [META.version]: String(graph.version),
    [META.module]: graph.module,
    [META.processScope]: graph.process_scope,
    [META.sapContext]: JSON.stringify(graph.sap_context),
    [META.direction]: graph.direction,
  })
  const root = append(xmlDocument, model, 'root', {})
  append(xmlDocument, root, 'mxCell', { id: '0' })
  append(xmlDocument, root, 'mxCell', { id: '1', parent: '0' })

  const laneBounds = laneGeometry(graph)
  for (const lane of graph.lanes) {
    const bounds = laneBounds.get(lane.id)!
    const cell = append(xmlDocument, root, 'mxCell', {
      id: lane.id,
      parent: '1',
      value: lane.label,
      vertex: '1',
      style: `swimlane;horizontal=1;startSize=34;fillColor=${lane.color};strokeColor=#8a9490;fontColor=#18332a;fontFamily=Microsoft YaHei;fontSize=13;`,
      [META.laneColor]: lane.color,
    })
    appendGeometry(xmlDocument, cell, bounds)
  }

  for (const node of graph.nodes) {
    const absolute = graph.layout[node.id] || { x: 80, y: 80 }
    const lane = node.lane_id ? laneBounds.get(node.lane_id) : null
    const size = nodeSize(node.type)
    const cell = append(xmlDocument, root, 'mxCell', {
      id: node.id,
      parent: node.lane_id || '1',
      value: node.label,
      vertex: '1',
      style: nodeStyle(node.type, node.sap),
      [META.nodeType]: node.type,
      [META.description]: node.description || '',
      [META.icon]: node.icon || '',
      [META.sap]: JSON.stringify(node.sap),
    })
    appendGeometry(xmlDocument, cell, {
      x: absolute.x - (lane?.x || 0),
      y: absolute.y - (lane?.y || 0),
      ...size,
    })
  }

  for (const edge of graph.edges) {
    const cell = append(xmlDocument, root, 'mxCell', {
      id: edge.id,
      parent: '1',
      source: edge.source,
      target: edge.target,
      value: edge.label || '',
      edge: '1',
      style: 'edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeWidth=1.5;endArrow=block;',
    })
    append(xmlDocument, cell, 'mxGeometry', { relative: '1', as: 'geometry' })
  }

  return `<?xml version="1.0" encoding="UTF-8"?>\n${new XMLSerializer().serializeToString(xmlDocument)}`
}

function parseXml(xml: string): Document {
  const parsed = new DOMParser().parseFromString(xml, 'application/xml')
  const error = parsed.querySelector('parsererror')
  if (error) throw new Error(`Draw.io XML 无法解析：${error.textContent?.trim() || '格式错误'}`)
  return parsed
}

function readCell(element: Element): CellRecord {
  return {
    element,
    id: element.getAttribute('id') || '',
    parent: element.getAttribute('parent'),
    source: element.getAttribute('source'),
    target: element.getAttribute('target'),
    value: element.getAttribute('value') || '',
    style: element.getAttribute('style') || '',
  }
}

function isLane(cell: CellRecord): boolean {
  return cell.element.getAttribute('vertex') === '1' && hasStyle(cell.style, 'swimlane')
}

function isSemanticNode(cell: CellRecord, laneIds: Set<string>, connectedIds: Set<string>): boolean {
  if (cell.element.getAttribute('vertex') !== '1' || isLane(cell)) return false
  return cell.element.hasAttribute(META.nodeType) || connectedIds.has(cell.id) || Boolean(cell.parent && laneIds.has(cell.parent) && !isDecoration(cell))
}

function isDecoration(cell: CellRecord): boolean {
  const label = cleanLabel(cell.value).toUpperCase()
  return label === 'SAP' || hasStyle(cell.style, 'text') || (!cell.source && !cell.target && /fontSize=(?:8|9|10);/.test(cell.style))
}

function toLane(cell: CellRecord): Swimlane {
  return {
    id: cell.id,
    label: cleanLabel(cell.value) || cell.id,
    color: cell.element.getAttribute(META.laneColor) || styleValue(cell.style, 'fillColor') || '#52796f',
  }
}

function toNode(cell: CellRecord, laneIds: Set<string>): FlowNode {
  const nodeType = cell.element.getAttribute(META.nodeType)
  return {
    id: cell.id,
    type: isNodeType(nodeType) ? nodeType : inferNodeType(cell.style),
    label: cleanLabel(cell.value) || cell.id,
    description: cell.element.getAttribute(META.description) || null,
    icon: (cell.element.getAttribute(META.icon) || null) as FlowNode['icon'],
    lane_id: cell.parent && laneIds.has(cell.parent) ? cell.parent : null,
    sap: parseJson<SapMetadata>(cell.element.getAttribute(META.sap), emptySapMetadata()),
  }
}

function inferNodeType(style: string): NodeType {
  if (hasStyle(style, 'rhombus')) return 'decision'
  if (hasStyle(style, 'ellipse')) return 'task'
  if (styleValue(style, 'fillColor') === '#e1d5e7') return 'subprocess'
  return 'task'
}

function nodeStyle(type: NodeType, sap: SapMetadata): string {
  const common = 'whiteSpace=wrap;html=1;fontFamily=Microsoft YaHei;fontSize=12;'
  if (type === 'start' || type === 'end') return `ellipse;${common}fillColor=#d5e8d4;strokeColor=#82b366;`
  if (type === 'decision') return `rhombus;${common}fillColor=#fff2cc;strokeColor=#d6b656;`
  if (type === 'subprocess') return `rounded=1;${common}fillColor=#e1d5e7;strokeColor=#9673a6;`
  if (sap.step_type === 'manual') return `rounded=0;${common}fillColor=#f5f5f5;strokeColor=#666666;dashed=1;`
  return `rounded=0;${common}fillColor=#dae8fc;strokeColor=#6c8ebf;`
}

function laneGeometry(graph: GraphDocument): Map<string, { x: number; y: number; width: number; height: number }> {
  const vertical = graph.direction === 'TB'
  return new Map(graph.lanes.map((lane, index) => [lane.id, vertical
    ? { x: 40 + index * 360, y: 70, width: 340, height: 1050 }
    : { x: 40, y: 70 + index * 220, width: 2050, height: 200 },
  ]))
}

function nodeSize(type: NodeType): { width: number; height: number } {
  if (type === 'start' || type === 'end') return { width: 110, height: 55 }
  if (type === 'decision') return { width: 140, height: 90 }
  return { width: 220, height: 75 }
}

function geometryPoint(element?: Element): { x: number; y: number } {
  const geometry = element?.querySelector(':scope > mxGeometry')
  return { x: numberAttribute(geometry, 'x', 0), y: numberAttribute(geometry, 'y', 0) }
}

function appendGeometry(document: Document, parent: Element, bounds: { x: number; y: number; width: number; height: number }): void {
  append(document, parent, 'mxGeometry', { ...stringValues(bounds), as: 'geometry' })
}

function append(document: Document, parent: Element, name: string, attributes: Record<string, string>): Element {
  const element = document.createElement(name)
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value)
  parent.appendChild(element)
  return element
}

function cleanLabel(value: string): string {
  const textarea = document.createElement('textarea')
  textarea.innerHTML = value.replace(/<br\s*\/?\s*>/gi, '\n').replace(/<[^>]+>/g, '')
  return textarea.value.replace(/\r/g, '').replace(/\n{3,}/g, '\n\n').trim()
}

function inferTitle(cells: CellRecord[]): string {
  const title = cells.find((cell) => cell.element.getAttribute('vertex') === '1' && hasStyle(cell.style, 'text'))
  return cleanLabel(title?.value || '') || '导入的 Draw.io 流程'
}

function inferDirection(nodes: FlowNode[], layout: Record<string, { x: number; y: number }>): 'TB' | 'LR' {
  if (nodes.length < 2) return 'TB'
  const xs = nodes.map((node) => layout[node.id]?.x || 0)
  const ys = nodes.map((node) => layout[node.id]?.y || 0)
  return Math.max(...xs) - Math.min(...xs) >= Math.max(...ys) - Math.min(...ys) ? 'LR' : 'TB'
}

function hasStyle(style: string, token: string): boolean {
  return style.split(';').some((part) => part === token || part.startsWith(`${token}=`))
}

function styleValue(style: string, key: string): string | null {
  const item = style.split(';').find((part) => part.startsWith(`${key}=`))
  return item ? item.slice(key.length + 1) : null
}

function isNodeType(value: string | null): value is NodeType {
  return value === 'start' || value === 'end' || value === 'task' || value === 'decision' || value === 'subprocess'
}

function parseJson<T>(value: string | null, fallback: T): T {
  if (!value) return fallback
  try { return JSON.parse(value) as T } catch { return fallback }
}

function numberAttribute(element: Element | null | undefined, key: string, fallback: number): number {
  const value = Number(element?.getAttribute(key))
  return Number.isFinite(value) ? value : fallback
}

function stringValues(values: Record<string, number>): Record<string, string> {
  return Object.fromEntries(Object.entries(values).map(([key, value]) => [key, String(value)]))
}
