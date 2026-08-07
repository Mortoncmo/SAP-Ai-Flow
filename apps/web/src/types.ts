export type NodeType = 'start' | 'end' | 'task' | 'decision' | 'subprocess'
export type Direction = 'TB' | 'LR'

export interface Position {
  x: number
  y: number
}

export interface FlowNode {
  id: string
  type: NodeType
  label: string
  description: string | null
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  label: string | null
}

export interface GraphDocument {
  schema_version: '1.0'
  graph_id: string
  version: number
  title: string
  direction: Direction
  nodes: FlowNode[]
  edges: FlowEdge[]
  layout: Record<string, Position>
}

export interface ModifyResponse {
  request_id: string
  base_version: number
  graph: GraphDocument
  applied_patch: {
    change_summary: string
    operations: unknown[]
  }
  warnings: string[]
  metrics: {
    provider: string
    model: string
    attempts: number
    latency_ms: number
  }
}
