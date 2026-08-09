import type { Node, NodeProps } from '@xyflow/react'
import { Handle, Position } from '@xyflow/react'
import { AlertTriangle } from 'lucide-react'
import type { Direction, GapStatus, MetadataStatus, NodeIcon, NodeType } from '../types'
import { NodeIconGlyph } from './nodeIcons'

export interface BusinessNodeData extends Record<string, unknown> {
  label: string
  description: string | null
  nodeType: NodeType
  direction: Direction
  icon: NodeIcon | null
  tcode: string | null
  tcodeStatus: MetadataStatus | null
  gapStatus: GapStatus
}

export type BusinessNodeModel = Node<BusinessNodeData, 'business'>

export function BusinessNode({ data, selected }: NodeProps<BusinessNodeModel>) {
  const horizontal = data.direction === 'LR'
  const acceptsIncoming = data.nodeType !== 'start'
  const allowsOutgoing = data.nodeType !== 'end'

  return (
    <div className={`business-node business-node--${data.nodeType}${selected ? ' is-selected' : ''}`}>
      {acceptsIncoming && (
        <Handle
          type="target"
          position={horizontal ? Position.Left : Position.Top}
          className="business-node__handle"
        />
      )}
      <span className="business-node__text">
        {data.icon && (
          <span className="business-node__icon">
            <NodeIconGlyph icon={data.icon} />
          </span>
        )}
        <strong>{data.label}</strong>
      </span>
      {data.tcode && (
        <small className={`business-node__tcode is-${data.tcodeStatus ?? 'pending_confirmation'}`}>
          {data.tcode}
        </small>
      )}
      {data.gapStatus !== 'none' && (
        <span className="business-node__gap" title={`GAP：${data.gapStatus}`} aria-label={`GAP ${data.gapStatus}`}>
          <AlertTriangle size={13} />
        </span>
      )}
      {allowsOutgoing && (
        <Handle
          type="source"
          position={horizontal ? Position.Right : Position.Bottom}
          className="business-node__handle"
        />
      )}
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
