import { useEffect, useState } from 'react'
import { Save, Trash2 } from 'lucide-react'
import { layoutGraph } from '../flow/layout'
import { nodeTypeLabel } from '../flow/BusinessNode'
import { useFlowStore } from '../stores/flowStore'
import type { NodeType } from '../types'

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

  useEffect(() => {
    if (!node) return
    setLabel(node.label)
    setDescription(node.description ?? '')
    setNodeType(node.type)
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
      </aside>
    )
  }

  const save = () => {
    const trimmed = label.trim()
    if (!trimmed) return
    commitGraph({
      ...graph,
      version: graph.version + 1,
      nodes: graph.nodes.map((item) =>
        item.id === node.id
          ? { ...item, label: trimmed, description: description.trim() || null, type: nodeType }
          : item,
      ),
    })
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
