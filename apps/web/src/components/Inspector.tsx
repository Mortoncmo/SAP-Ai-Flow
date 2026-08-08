import { useEffect, useState } from 'react'
import { Plus, Save, Trash2 } from 'lucide-react'
import { createId } from '../data'
import { layoutGraph } from '../flow/layout'
import { nodeTypeLabel } from '../flow/BusinessNode'
import { nodeIconLabels } from '../flow/nodeIcons'
import { useFlowStore } from '../stores/flowStore'
import { nodeIconKeys } from '../types'
import type { NodeIcon, NodeType, Swimlane } from '../types'

interface InspectorProps {
  selectedNodeId: string | null
  onClearSelection: () => void
}

export function Inspector({ selectedNodeId, onClearSelection }: InspectorProps) {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const node = graph.nodes.find((item) => item.id === selectedNodeId)
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [nodeType, setNodeType] = useState<NodeType>('task')
  const [icon, setIcon] = useState<NodeIcon | ''>('')
  const [laneId, setLaneId] = useState('')

  useEffect(() => {
    if (!node) return
    setLabel(node.label)
    setDescription(node.description ?? '')
    setNodeType(node.type)
    setIcon(node.icon ?? '')
    setLaneId(node.lane_id ?? '')
  }, [node])

  if (!node) {
    const decisions = graph.nodes.filter((item) => item.type === 'decision').length
    return (
      <aside className="inspector" aria-label="流程概况">
        <div className="inspector__heading">
          <span>流程概况</span>
          <small>v{graph.version}</small>
        </div>
        <dl className="stats-grid">
          <div>
            <dt>节点</dt>
            <dd>{graph.nodes.length}</dd>
          </div>
          <div>
            <dt>连线</dt>
            <dd>{graph.edges.length}</dd>
          </div>
          <div>
            <dt>判断</dt>
            <dd>{decisions}</dd>
          </div>
          <div>
            <dt>方向</dt>
            <dd>{graph.direction}</dd>
          </div>
        </dl>
        <div className="inspector__meta">
          <span>流程 ID</span>
          <code>{graph.graph_id}</code>
        </div>
        <LaneManager />
      </aside>
    )
  }

  const save = () => {
    const trimmed = label.trim()
    if (!trimmed) return
    const nextGraph = {
      ...graph,
      version: graph.version + 1,
      nodes: graph.nodes.map((item) =>
        item.id === node.id
          ? {
              ...item,
              label: trimmed,
              description: description.trim() || null,
              type: nodeType,
              icon: icon || null,
              lane_id: laneId || null,
            }
          : item,
      ),
    }
    const requiresLayout = node.type !== nodeType || node.lane_id !== (laneId || null)
    commitGraph(requiresLayout ? layoutGraph(nextGraph) : nextGraph)
  }

  const remove = () => {
    commitGraph(
      layoutGraph({
        ...graph,
        version: graph.version + 1,
        nodes: graph.nodes.filter((item) => item.id !== node.id),
        edges: graph.edges.filter((edge) => edge.source !== node.id && edge.target !== node.id),
        layout: Object.fromEntries(
          Object.entries(graph.layout).filter(([nodeId]) => nodeId !== node.id),
        ),
      }),
    )
    onClearSelection()
  }

  return (
    <aside className="inspector" aria-label="节点属性">
      <div className="inspector__heading">
        <span>节点属性</span>
        <small>{nodeTypeLabel[node.type]}</small>
      </div>
      <form
        className="inspector-form"
        onSubmit={(event) => {
          event.preventDefault()
          save()
        }}
      >
        <label>
          名称
          <input value={label} maxLength={200} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          类型
          <select value={nodeType} onChange={(event) => setNodeType(event.target.value as NodeType)}>
            {Object.entries(nodeTypeLabel).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <label>
          图标
          <select value={icon} onChange={(event) => setIcon(event.target.value as NodeIcon | '')}>
            <option value="">无图标</option>
            {nodeIconKeys.map((value) => (
              <option key={value} value={value}>
                {nodeIconLabels[value]}
              </option>
            ))}
          </select>
        </label>
        <label>
          泳道
          <select value={laneId} onChange={(event) => setLaneId(event.target.value)}>
            <option value="">未分配</option>
            {graph.lanes.map((lane) => (
              <option key={lane.id} value={lane.id}>
                {lane.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          说明
          <textarea
            value={description}
            rows={5}
            maxLength={1000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="inspector-form__actions">
          <button type="button" className="icon-button danger" onClick={remove} title="删除节点">
            <Trash2 size={17} />
            <span>删除</span>
          </button>
          <button type="submit" className="command-button compact">
            <Save size={17} />
            <span>保存</span>
          </button>
        </div>
      </form>
    </aside>
  )
}

const laneColors = ['#52796f', '#5b7394', '#a36f3f', '#7b668f', '#547f86']

function LaneManager() {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)

  const updateLane = (id: string, changes: Partial<Pick<Swimlane, 'label' | 'color'>>) => {
    commitGraph(
      layoutGraph({
        ...graph,
        version: graph.version + 1,
        lanes: graph.lanes.map((lane) => (lane.id === id ? { ...lane, ...changes } : lane)),
      }),
    )
  }

  const removeLane = (lane: Swimlane) => {
    const assigned = graph.nodes.filter((node) => node.lane_id === lane.id).length
    if (assigned > 0 && !window.confirm(`“${lane.label}”中有 ${assigned} 个节点，删除后这些节点将变为未分配。`)) {
      return
    }
    commitGraph(
      layoutGraph({
        ...graph,
        version: graph.version + 1,
        lanes: graph.lanes.filter((item) => item.id !== lane.id),
        nodes: graph.nodes.map((node) =>
          node.lane_id === lane.id ? { ...node, lane_id: null } : node,
        ),
      }),
    )
  }

  return (
    <section className="lane-manager" aria-label="泳道管理">
      <div className="lane-manager__heading">
        <span>泳道</span>
        <button
          type="button"
          className="icon-button"
          title="增加泳道"
          aria-label="增加泳道"
          disabled={graph.lanes.length >= 20}
          onClick={() => {
            const number = graph.lanes.length + 1
            commitGraph(
              layoutGraph({
                ...graph,
                version: graph.version + 1,
                lanes: [
                  ...graph.lanes,
                  {
                    id: createId('lane'),
                    label: `泳道 ${number}`,
                    color: laneColors[graph.lanes.length % laneColors.length],
                  },
                ],
              }),
            )
          }}
        >
          <Plus size={16} />
        </button>
      </div>
      {graph.lanes.length === 0 ? (
        <p className="lane-manager__empty">尚未创建泳道</p>
      ) : (
        <div className="lane-manager__list">
          {graph.lanes.map((lane) => (
            <LaneEditor
              key={lane.id}
              lane={lane}
              onUpdate={(changes) => updateLane(lane.id, changes)}
              onRemove={() => removeLane(lane)}
            />
          ))}
        </div>
      )}
    </section>
  )
}

function LaneEditor({
  lane,
  onUpdate,
  onRemove,
}: {
  lane: Swimlane
  onUpdate: (changes: Partial<Pick<Swimlane, 'label' | 'color'>>) => void
  onRemove: () => void
}) {
  const [label, setLabel] = useState(lane.label)

  useEffect(() => setLabel(lane.label), [lane.label])

  const commitLabel = () => {
    const trimmed = label.trim()
    if (!trimmed) {
      setLabel(lane.label)
    } else if (trimmed !== lane.label) {
      onUpdate({ label: trimmed })
    }
  }

  return (
    <div className="lane-editor">
      <input
        className="lane-editor__color"
        type="color"
        value={lane.color}
        title={`${lane.label}颜色`}
        aria-label={`${lane.label}颜色`}
        onChange={(event) => onUpdate({ color: event.target.value })}
      />
      <input
        className="lane-editor__name"
        value={label}
        maxLength={80}
        aria-label="泳道名称"
        onChange={(event) => setLabel(event.target.value)}
        onBlur={commitLabel}
        onKeyDown={(event) => {
          if (event.key === 'Enter') event.currentTarget.blur()
        }}
      />
      <button
        type="button"
        className="icon-button danger"
        title={`删除${lane.label}泳道`}
        aria-label={`删除${lane.label}泳道`}
        onClick={onRemove}
      >
        <Trash2 size={15} />
      </button>
    </div>
  )
}
