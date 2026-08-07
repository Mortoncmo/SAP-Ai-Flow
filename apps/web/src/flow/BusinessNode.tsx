import type { Node, NodeProps } from '@xyflow/react'
import { Handle, Position } from '@xyflow/react'
import {
  CirclePlay,
  CircleStop,
  ClipboardCheck,
  GitBranch,
  Layers3,
} from 'lucide-react'
import type { Direction, NodeType } from '../types'

export interface BusinessNodeData extends Record<string, unknown> {
  label: string
  description: string | null
  nodeType: NodeType
  direction: Direction
}

export type BusinessNodeModel = Node<BusinessNodeData, 'business'>

const iconByType = {
  start: CirclePlay,
  end: CircleStop,
  task: ClipboardCheck,
  decision: GitBranch,
  subprocess: Layers3,
}

export function BusinessNode({ data, selected }: NodeProps<BusinessNodeModel>) {
  const Icon = iconByType[data.nodeType]
  const horizontal = data.direction === 'LR'

  return (
    <div className={`business-node business-node--${data.nodeType}${selected ? ' is-selected' : ''}`}>
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        className="business-node__handle"
      />
      <span className="business-node__icon" aria-hidden="true">
        <Icon size={18} strokeWidth={2} />
      </span>
      <span className="business-node__text">
        <strong>{data.label}</strong>
        <small>{nodeTypeLabel[data.nodeType]}</small>
      </span>
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        className="business-node__handle"
      />
    </div>
  )
}

export const nodeTypeLabel: Record<NodeType, string> = {
  start: '开始事件',
  end: '结束事件',
  task: '处理任务',
  decision: '条件判断',
  subprocess: '子流程',
}
