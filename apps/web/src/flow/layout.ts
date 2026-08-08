import dagre from '@dagrejs/dagre'
import type { GraphDocument, NodeType, Position } from '../types'

export interface NodeDimensions {
  width: number
  height: number
}

const NODE_DIMENSIONS: Record<NodeType, NodeDimensions> = {
  start: { width: 164, height: 58 },
  end: { width: 164, height: 58 },
  task: { width: 190, height: 70 },
  decision: { width: 176, height: 112 },
  subprocess: { width: 190, height: 76 },
}

const LANE_CROSS_SIZE = 276
const LANE_GAP = 24
const LANE_HEADER_SIZE = 42
const LANE_PADDING = 52

export interface LaneFrame {
  id: string
  x: number
  y: number
  width: number
  height: number
}

export function nodeDimensions(type: NodeType): NodeDimensions {
  return { ...NODE_DIMENSIONS[type] }
}

export function layoutGraph(graph: GraphDocument): GraphDocument {
  if (graph.nodes.length === 0) return { ...graph, layout: {} }

  const layout = new dagre.graphlib.Graph()
  layout.setDefaultEdgeLabel(() => ({}))
  layout.setGraph({
    rankdir: graph.direction,
    ranksep: graph.direction === 'TB' ? 78 : 110,
    nodesep: 44,
    edgesep: 28,
    marginx: 48,
    marginy: 48,
  })

  graph.nodes.forEach((node) => {
    layout.setNode(node.id, nodeDimensions(node.type))
  })
  graph.edges.forEach((edge) => layout.setEdge(edge.source, edge.target))
  dagre.layout(layout)

  const dagreLayout = Object.fromEntries(
    graph.nodes.map((node) => {
      const position = layout.node(node.id) as { x: number; y: number }
      const dimensions = nodeDimensions(node.type)
      return [
        node.id,
        {
          x: position.x - dimensions.width / 2,
          y: position.y - dimensions.height / 2,
        },
      ]
    }),
  )

  const nextLayout = applySwimlaneLayout(graph, dagreLayout)

  return { ...graph, layout: nextLayout }
}

export function laneFrames(graph: GraphDocument): LaneFrame[] {
  if (graph.lanes.length === 0) return []

  if (graph.direction === 'TB') {
    const contentHeight = Math.max(
      560,
      ...graph.nodes.map((node) => {
        const position = graph.layout[node.id] ?? { x: 0, y: LANE_HEADER_SIZE + LANE_PADDING }
        return position.y + nodeDimensions(node.type).height + LANE_PADDING
      }),
    )
    return graph.lanes.map((lane, index) => ({
      id: lane.id,
      x: index * (LANE_CROSS_SIZE + LANE_GAP),
      y: 0,
      width: LANE_CROSS_SIZE,
      height: contentHeight,
    }))
  }

  const contentWidth = Math.max(
    760,
    ...graph.nodes.map((node) => {
      const position = graph.layout[node.id] ?? { x: LANE_PADDING, y: 0 }
      return position.x + nodeDimensions(node.type).width + LANE_PADDING
    }),
  )
  return graph.lanes.map((lane, index) => ({
    id: lane.id,
    x: 0,
    y: index * (LANE_CROSS_SIZE + LANE_GAP),
    width: contentWidth,
    height: LANE_CROSS_SIZE,
  }))
}

export function laneIdAtPosition(
  graph: GraphDocument,
  position: Position,
  dimensions: NodeDimensions,
): string | null {
  const center = {
    x: position.x + dimensions.width / 2,
    y: position.y + dimensions.height / 2,
  }
  const frame = laneFrames(graph).find(
    (lane) =>
      center.x >= lane.x &&
      center.x <= lane.x + lane.width &&
      center.y >= lane.y &&
      center.y <= lane.y + lane.height,
  )
  return frame?.id ?? null
}

function applySwimlaneLayout(
  graph: GraphDocument,
  dagreLayout: Record<string, Position>,
): Record<string, Position> {
  if (graph.lanes.length === 0) return dagreLayout

  const laneIndex = new Map(graph.lanes.map((lane, index) => [lane.id, index]))
  if (graph.direction === 'TB') {
    const minY = Math.min(...Object.values(dagreLayout).map((position) => position.y))
    return Object.fromEntries(
      graph.nodes.map((node) => {
        const dimensions = nodeDimensions(node.type)
        const index = laneIndex.get(node.lane_id ?? '') ?? 0
        return [
          node.id,
          {
            x: index * (LANE_CROSS_SIZE + LANE_GAP) + (LANE_CROSS_SIZE - dimensions.width) / 2,
            y: dagreLayout[node.id].y - minY + LANE_HEADER_SIZE + LANE_PADDING,
          },
        ]
      }),
    )
  }

  const minX = Math.min(...Object.values(dagreLayout).map((position) => position.x))
  return Object.fromEntries(
    graph.nodes.map((node) => {
      const dimensions = nodeDimensions(node.type)
      const index = laneIndex.get(node.lane_id ?? '') ?? 0
      return [
        node.id,
        {
          x: dagreLayout[node.id].x - minX + LANE_PADDING,
          y:
            index * (LANE_CROSS_SIZE + LANE_GAP) +
            LANE_HEADER_SIZE +
            (LANE_CROSS_SIZE - LANE_HEADER_SIZE - dimensions.height) / 2,
        },
      ]
    }),
  )
}
