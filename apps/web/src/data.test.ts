import { describe, expect, it } from 'vitest'
import { createEmptyGraph, emptySapMetadata, normalizeGraph } from './data'
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
        sap: emptySapMetadata(),
      },
    ]

    expect(normalizeGraph(graph).nodes[0].lane_id).toBeNull()
  })

  it('uses a safe default for invalid imported lane colors', () => {
    const graph = createEmptyGraph()
    graph.lanes = [{ id: 'lane', label: '业务', color: 'not-a-color' }]

    expect(normalizeGraph(graph).lanes[0].color).toBe('#52796f')
  })

  it('upgrades a 1.0 graph and preserves its topology while adding SAP defaults', () => {
    const legacy = {
      schema_version: '1.0',
      graph_id: 'legacy',
      version: 4,
      title: '旧流程',
      direction: 'TB',
      nodes: [{ id: 'start', type: 'start', label: '开始', description: null }],
      edges: [],
      lanes: [],
      layout: { start: { x: 12, y: 24 } },
    }

    const normalized = normalizeGraph(legacy)

    expect(normalized.schema_version).toBe('2.0')
    expect(normalized.module).toBe('MM')
    expect(normalized.process_scope).toBe('P2P')
    expect(normalized.nodes[0].sap.gap.status).toBe('none')
    expect(normalized.layout.start).toEqual({ x: 12, y: 24 })
  })
})
