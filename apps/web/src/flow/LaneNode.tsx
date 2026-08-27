import type { CSSProperties } from 'react'
import type { Node, NodeProps } from '@xyflow/react'
import type { Direction } from '../types'

export interface LaneNodeData extends Record<string, unknown> {
  label: string
  color: string
  direction: Direction
  nodeCount: number
}

export type LaneNodeModel = Node<LaneNodeData, 'lane'>

export function LaneNode({ data }: NodeProps<LaneNodeModel>) {
  return (
    <div
      className={`swimlane-node swimlane-node--${data.direction.toLowerCase()}`}
      style={{ '--lane-color': data.color } as CSSProperties}
    >
      <div className="swimlane-node__heading">
        <span className="swimlane-node__swatch" />
        <strong>{data.label}</strong>
        <small>{data.nodeCount}</small>
      </div>
    </div>
  )
}
