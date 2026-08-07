import dagre from '@dagrejs/dagre'
import type { GraphDocument } from '../types'

export const NODE_WIDTH = 192
export const NODE_HEIGHT = 72

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
    layout.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT })
  })
  graph.edges.forEach((edge) => layout.setEdge(edge.source, edge.target))
  dagre.layout(layout)

  const nextLayout = Object.fromEntries(
    graph.nodes.map((node) => {
      const position = layout.node(node.id) as { x: number; y: number }
      return [
        node.id,
        {
          x: position.x - NODE_WIDTH / 2,
          y: position.y - NODE_HEIGHT / 2,
        },
      ]
    }),
  )

  return { ...graph, layout: nextLayout }
}
