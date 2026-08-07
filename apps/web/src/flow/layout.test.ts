import { describe, expect, it } from 'vitest'
import { createSampleGraph } from '../data'
import { layoutGraph, nodeDimensions } from './layout'

describe('flow layout', () => {
  it('uses standard dimensions for each flowchart symbol', () => {
    expect(nodeDimensions('start')).toEqual({ width: 164, height: 58 })
    expect(nodeDimensions('task')).toEqual({ width: 190, height: 70 })
    expect(nodeDimensions('decision')).toEqual({ width: 176, height: 112 })
    expect(nodeDimensions('subprocess')).toEqual({ width: 190, height: 76 })
  })

  it('assigns a distinct position to every sample node', () => {
    const graph = layoutGraph(createSampleGraph())
    const positions = graph.nodes.map((node) => {
      const position = graph.layout[node.id]
      return `${position.x}:${position.y}`
    })

    expect(new Set(positions).size).toBe(graph.nodes.length)
  })
})
