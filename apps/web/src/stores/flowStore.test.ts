import { beforeEach, describe, expect, it } from 'vitest'
import { createEmptyGraph } from '../data'
import { useFlowStore } from './flowStore'

describe('flow store history', () => {
  beforeEach(() => {
    localStorage.clear()
    useFlowStore.getState().reset(createEmptyGraph())
  })

  it('undoes and redoes a committed graph', () => {
    const original = useFlowStore.getState().graph
    const changed = { ...original, version: 1, title: '采购审批流程' }

    useFlowStore.getState().commitGraph(changed)
    expect(useFlowStore.getState().graph.title).toBe('采购审批流程')

    useFlowStore.getState().undo()
    expect(useFlowStore.getState().graph.title).toBe('未命名流程')

    useFlowStore.getState().redo()
    expect(useFlowStore.getState().graph.title).toBe('采购审批流程')
  })

  it('clears redo history when a new change is committed', () => {
    const original = useFlowStore.getState().graph
    useFlowStore.getState().commitGraph({ ...original, version: 1, title: 'A' })
    useFlowStore.getState().undo()
    useFlowStore.getState().commitGraph({ ...original, version: 2, title: 'B' })

    expect(useFlowStore.getState().future).toHaveLength(0)
  })
})
