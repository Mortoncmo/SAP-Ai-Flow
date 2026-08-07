import dagre from '@dagrejs/dagre'
import type { GraphDocument, NodeType } from '../types'

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

  const nextLayout = Object.fromEntries(
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

  return { ...graph, layout: nextLayout }
}
