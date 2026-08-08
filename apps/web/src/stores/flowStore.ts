import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { createSampleGraph, normalizeGraph } from '../data'
import { layoutGraph } from '../flow/layout'
import type { GraphDocument } from '../types'

const HISTORY_LIMIT = 50

interface FlowState {
  graph: GraphDocument
  past: GraphDocument[]
  future: GraphDocument[]
  commitGraph: (graph: GraphDocument) => void
  replaceGraph: (graph: GraphDocument) => void
  undo: () => void
  redo: () => void
  reset: (graph?: GraphDocument) => void
}

const initialGraph = layoutGraph(createSampleGraph())

export const useFlowStore = create<FlowState>()(
  persist(
    (set) => ({
      graph: initialGraph,
      past: [],
      future: [],
      commitGraph: (graph) =>
        set((state) => ({
          graph,
          past: [...state.past.slice(-(HISTORY_LIMIT - 1)), state.graph],
          future: [],
        })),
      replaceGraph: (graph) => set({ graph }),
      undo: () =>
        set((state) => {
          if (state.past.length === 0) return state
          const previous = state.past[state.past.length - 1]
          return {
            graph: previous,
            past: state.past.slice(0, -1),
            future: [state.graph, ...state.future].slice(0, HISTORY_LIMIT),
          }
        }),
      redo: () =>
        set((state) => {
          if (state.future.length === 0) return state
          const next = state.future[0]
          return {
            graph: next,
            past: [...state.past.slice(-(HISTORY_LIMIT - 1)), state.graph],
            future: state.future.slice(1),
          }
        }),
      reset: (graph = initialGraph) => set({ graph, past: [], future: [] }),
    }),
    {
      name: 'sap-ai-flow-state',
      version: 3,
      partialize: (state) => ({ graph: state.graph }),
      migrate: (persistedState) => {
        const state = persistedState as { graph?: GraphDocument }
        return {
          graph: state.graph ? layoutGraph(normalizeGraph(state.graph)) : initialGraph,
        }
      },
    },
  ),
)
