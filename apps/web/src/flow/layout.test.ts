import { describe, expect, it } from 'vitest'
import { createSampleGraph } from '../data'
import { laneFrames, laneIdAtPosition, layoutGraph, nodeDimensions } from './layout'

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

  it('places assigned nodes inside their swimlane frames', () => {
    const graph = layoutGraph(createSampleGraph())
    const frames = new Map(laneFrames(graph).map((frame) => [frame.id, frame]))

    expect(frames.size).toBe(5)
    graph.nodes.forEach((node) => {
      const frame = frames.get(node.lane_id!)!
      const position = graph.layout[node.id]
      const dimensions = nodeDimensions(node.type)
      expect(position.x + dimensions.width / 2).toBeGreaterThanOrEqual(frame.x)
      expect(position.x + dimensions.width / 2).toBeLessThanOrEqual(frame.x + frame.width)
      expect(laneIdAtPosition(graph, position, dimensions)).toBe(node.lane_id)
    })
  })

  it('switches to horizontal swimlanes for left-to-right flows', () => {
    const graph = layoutGraph({ ...createSampleGraph(), direction: 'LR' })
    const frames = laneFrames(graph)

    expect(frames[1].y).toBeGreaterThan(frames[0].y)
    expect(frames[0].x).toBe(0)
    expect(frames[0].width).toBeGreaterThan(frames[0].height)
  })
})
