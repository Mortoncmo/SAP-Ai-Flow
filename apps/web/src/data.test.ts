import { describe, expect, it } from 'vitest'
import { createEmptyGraph, normalizeGraph } from './data'
import type { GraphDocument } from './types'

describe('normalizeGraph', () => {
  it('migrates graphs created before icons and swimlanes were introduced', () => {
    const legacy = {
      ...createEmptyGraph(),
      nodes: [{ id: 'task', type: 'task', label: '旧节点', description: null }],
    }
    delete (legacy as Partial<GraphDocument>).lanes

    const normalized = normalizeGraph(legacy as GraphDocument)

    expect(normalized.lanes).toEqual([])
    expect(normalized.nodes[0]).toMatchObject({ icon: null, lane_id: null })
  })

  it('clears stale lane references during import', () => {
    const graph = createEmptyGraph()
    graph.nodes = [
      {
        id: 'task',
        type: 'task',
        label: '待处理',
        description: null,
        icon: 'clipboard-check',
        lane_id: 'missing-lane',
      },
    ]

    expect(normalizeGraph(graph).nodes[0].lane_id).toBeNull()
  })

  it('uses a safe default for invalid imported lane colors', () => {
    const graph = createEmptyGraph()
    graph.lanes = [{ id: 'lane', label: '业务', color: 'not-a-color' }]

    expect(normalizeGraph(graph).lanes[0].color).toBe('#52796f')
  })
})
