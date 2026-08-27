import { useEffect, useState } from 'react'
import { AlertTriangle, Plus, Save, Search, Trash2 } from 'lucide-react'
import { analyzeGapCandidate, decideGap, searchSapKnowledge } from '../api/client'
import { createId, normalizeGraph } from '../data'
import { nodeTypeLabel } from '../flow/BusinessNode'
import { nodeIconLabels } from '../flow/nodeIcons'
import { layoutGraph as applyLayout } from '../flow/layout'
import { useFlowStore } from '../stores/flowStore'
import { gapStatusKeys, metadataStatusKeys, nodeIconKeys, sapStepTypeKeys } from '../types'
import type {
  BestPracticeReference,
  ConfigurationPoint,
  GapStatus,
  FlowEdge,
  GraphDocument,
  KnowledgeEvidence,
  MetadataStatus,
  NodeIcon,
  NodeType,
  SapMetadata,
  SapStepType,
  Swimlane,
  TCodeReference,
} from '../types'

interface InspectorProps {
  selectedNodeId: string | null
  selectedEdgeId: string | null
  onClearSelection: () => void
  projectId?: string
  processId?: string
  baseRevision?: number | null
  onPersistedGraph?: (graph: GraphDocument, revision: number) => void
  readOnly?: boolean
  canApprove?: boolean
}

const sapStepTypeLabel: Record<SapStepType, string> = {
  transaction: '事务处理',
  approval: '审批',
  validation: '校验',
  manual: '人工处理',
  integration: '系统集成',
}

const metadataStatusLabel: Record<MetadataStatus, string> = {
  suggested: '建议',
  pending_confirmation: '待确认',
  verified: '已验证',
}

const gapStatusLabel: Record<GapStatus, string> = {
  none: '无 GAP',
  candidate: '候选',
  confirmed: '已确认',
  rejected: '已驳回',
  resolved: '已解决',
}

export function Inspector({
  selectedNodeId,
  selectedEdgeId,
  onClearSelection,
  projectId,
  processId,
  baseRevision,
  onPersistedGraph,
  readOnly = false,
  canApprove = true,
}: InspectorProps) {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const node = graph.nodes.find((item) => item.id === selectedNodeId)
  const edge = graph.edges.find((item) => item.id === selectedEdgeId)
  const [label, setLabel] = useState('')
  const [description, setDescription] = useState('')
  const [nodeType, setNodeType] = useState<NodeType>('task')
  const [icon, setIcon] = useState<NodeIcon | ''>('')
  const [laneId, setLaneId] = useState('')
  const [stepType, setStepType] = useState<SapStepType | ''>('')
  const [tcodeText, setTCodeText] = useState('')
  const [fioriText, setFioriText] = useState('')
  const [rolesText, setRolesText] = useState('')
  const [configurationText, setConfigurationText] = useState('')
  const [bestPracticeText, setBestPracticeText] = useState('')
  const [gapStatus, setGapStatus] = useState<GapStatus>('none')
  const [gapCategory, setGapCategory] = useState('')
  const [gapDescription, setGapDescription] = useState('')
  const [gapRecommendation, setGapRecommendation] = useState('')
  const [gapOwner, setGapOwner] = useState('')
  const [validationError, setValidationError] = useState('')
  const [knowledgeEvidence, setKnowledgeEvidence] = useState<KnowledgeEvidence[]>([])
  const [knowledgeMessage, setKnowledgeMessage] = useState('')
  const [knowledgePending, setKnowledgePending] = useState(false)

  useEffect(() => {
    if (!node) return
    setLabel(node.label)
    setDescription(node.description ?? '')
    setNodeType(node.type)
    setIcon(node.icon ?? '')
    setLaneId(node.lane_id ?? '')
    setStepType(node.sap.step_type ?? '')
    setTCodeText(node.sap.tcodes.map((item) => item.code).join(', '))
    setFioriText(
      node.sap.fiori_apps
        .map((item) => (item.app_id ? `${item.app_id} | ${item.name}` : item.name))
        .join('\n'),
    )
    setRolesText(node.sap.roles.join(', '))
    setConfigurationText(node.sap.configuration_points.map((item) => item.label).join('\n'))
    setBestPracticeText(
      node.sap.best_practice_refs
        .map((item) => `${item.scope_item} | ${item.step}`)
        .join('\n'),
    )
    setGapStatus(node.sap.gap.status)
    setGapCategory(node.sap.gap.category ?? '')
    setGapDescription(node.sap.gap.description ?? '')
    setGapRecommendation(node.sap.gap.recommendation ?? '')
    setGapOwner(node.sap.gap.owner ?? '')
    setValidationError('')
    setKnowledgeEvidence([])
    setKnowledgeMessage('')
  }, [node])

  if (edge) {
    return (
      <EdgeInspector
        edge={edge}
        readOnly={readOnly}
        onClearSelection={onClearSelection}
      />
    )
  }

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
        <SapContextManager readOnly={readOnly} />
        <LaneManager readOnly={readOnly} />
      </aside>
    )
  }

  const save = () => {
    if (readOnly) return
    const trimmed = label.trim()
    if (!trimmed) return
    if ((gapStatus === 'candidate' || gapStatus === 'confirmed') && !gapDescription.trim()) {
      setValidationError('候选或已确认 GAP 必须填写差异描述。')
      return
    }
    if (
      !canApprove &&
      gapStatus !== node.sap.gap.status &&
      ['confirmed', 'rejected', 'resolved'].includes(gapStatus)
    ) {
      setValidationError('当前项目角色不能确认、驳回或解决 GAP。')
      return
    }
    if (
      gapStatus === 'confirmed' &&
      node.sap.gap.status !== 'confirmed' &&
      !window.confirm('确认将此 GAP 标记为已确认？该状态代表顾问已作出判断。')
    ) {
      return
    }

    if (
      processId &&
      baseRevision !== null &&
      baseRevision !== undefined &&
      gapStatus !== node.sap.gap.status &&
      ['confirmed', 'rejected', 'resolved'].includes(gapStatus)
    ) {
      void decideGap(processId, node.id, baseRevision, gapStatus as 'confirmed' | 'rejected' | 'resolved', gapDescription.trim() || '顾问确认 GAP 状态')
        .then((result) => {
          onPersistedGraph?.(result.graph, result.revision_no)
          setValidationError('')
        })
        .catch((error) => setValidationError(error instanceof Error ? error.message : 'GAP 决策保存失败。'))
      return
    }

    const sap = buildSapMetadata(node.sap, {
      stepType: stepType || null,
      tcodeText,
      fioriText,
      rolesText,
      configurationText,
      bestPracticeText,
      gap: {
        ...node.sap.gap,
        status: gapStatus,
        category: gapCategory.trim() || null,
        description: gapDescription.trim() || null,
        recommendation: gapRecommendation.trim() || null,
        owner: gapOwner.trim() || null,
      },
    })
    const nextGraph = normalizeGraph({
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
              sap,
            }
          : item,
      ),
    })
    const requiresLayout = node.type !== nodeType || node.lane_id !== (laneId || null)
    commitGraph(requiresLayout ? applyLayout(nextGraph) : nextGraph)
    setValidationError('')
  }

  const remove = () => {
    if (readOnly) return
    commitGraph(
      applyLayout({
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

  const searchKnowledge = async () => {
    if (readOnly) return
    setKnowledgePending(true)
    setValidationError('')
    try {
      const query = [label, tcodeText, bestPracticeText, description].filter(Boolean).join(' ')
      const result = await searchSapKnowledge(graph, query, projectId)
      setKnowledgeEvidence(result.evidence)
      setKnowledgeMessage(result.warnings.join(' ') || `找到 ${result.evidence.length} 条证据。`)
      if (result.evidence.length > 0) {
        const evidenceRef = result.evidence[0].evidence_ref
        const updatedSap = buildSapMetadata(node.sap, {
          stepType: stepType || null,
          tcodeText,
          fioriText,
          rolesText,
          configurationText,
          bestPracticeText,
          gap: node.sap.gap,
        })
        const sap = {
          ...updatedSap,
          tcodes: updatedSap.tcodes.map((item) => ({
            ...item,
            status: item.status === 'verified' ? item.status : ('pending_confirmation' as const),
            evidence_ref: item.evidence_ref ?? evidenceRef,
          })),
          best_practice_refs: updatedSap.best_practice_refs.map((item) => ({
            ...item,
            evidence_ref: item.evidence_ref ?? evidenceRef,
          })),
        }
        commitGraph({
          ...graph,
          version: graph.version + 1,
          nodes: graph.nodes.map((item) => (item.id === node.id ? { ...item, sap } : item)),
        })
      }
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : '知识检索失败。')
    } finally {
      setKnowledgePending(false)
    }
  }

  const analyzeGap = async () => {
    if (readOnly) return
    const requirement = gapDescription.trim() || description.trim() || label.trim()
    if (!requirement) {
      setValidationError('请先填写节点说明或 GAP 差异描述。')
      return
    }
    setKnowledgePending(true)
    setValidationError('')
    try {
      const result = await analyzeGapCandidate(graph, requirement, projectId)
      setKnowledgeEvidence(result.evidence)
      setKnowledgeMessage(result.warnings.join(' '))
      if (result.gap) {
        setGapStatus('candidate')
        setGapCategory(result.gap.category ?? '')
        setGapDescription(result.gap.description ?? requirement)
        setGapRecommendation(result.gap.recommendation ?? '')
      }
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : 'GAP 分析失败。')
    } finally {
      setKnowledgePending(false)
    }
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
        <fieldset className="inspector-form__fieldset" disabled={readOnly}>
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
            rows={4}
            maxLength={1000}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>

        <section className="inspector-form__section" aria-label="SAP 元数据">
          <div className="inspector-form__section-heading">SAP 元数据</div>
          <label>
            步骤类型
            <select value={stepType} onChange={(event) => setStepType(event.target.value as SapStepType | '')}>
              <option value="">未设置</option>
              {sapStepTypeKeys.map((value) => (
                <option key={value} value={value}>
                  {sapStepTypeLabel[value]}
                </option>
              ))}
            </select>
          </label>
          <label>
            T-Code（逗号分隔）
            <input value={tcodeText} maxLength={400} onChange={(event) => setTCodeText(event.target.value)} />
          </label>
          <label>
            Fiori App（每行：ID | 名称）
            <textarea value={fioriText} rows={2} maxLength={600} onChange={(event) => setFioriText(event.target.value)} />
          </label>
          <label>
            业务角色（逗号分隔）
            <input value={rolesText} maxLength={300} onChange={(event) => setRolesText(event.target.value)} />
          </label>
          <label>
            配置点（每行一项）
            <textarea
              value={configurationText}
              rows={3}
              maxLength={800}
              onChange={(event) => setConfigurationText(event.target.value)}
            />
          </label>
          <label>
            Best Practice（每行：Scope Item | 步骤）
            <textarea
              value={bestPracticeText}
              rows={3}
              maxLength={800}
              onChange={(event) => setBestPracticeText(event.target.value)}
            />
          </label>
          <EvidenceSummary sap={node.sap} />
          <button
            type="button"
            className="secondary-button"
            disabled={knowledgePending || readOnly}
            onClick={() => void searchKnowledge()}
          >
            <Search size={15} />
            <span>{knowledgePending ? '检索中' : '匹配 SAP 知识'}</span>
          </button>
          {knowledgeEvidence.length > 0 && <KnowledgeEvidenceList evidence={knowledgeEvidence} />}
          {knowledgeMessage && <p className="inspector-form__notice">{knowledgeMessage}</p>}
        </section>

        <section className="inspector-form__section" aria-label="GAP 管理">
          <div className="inspector-form__section-heading">GAP 管理</div>
          <label>
            状态
            <select value={gapStatus} onChange={(event) => setGapStatus(event.target.value as GapStatus)}>
              {gapStatusKeys.map((value) => (
                <option
                  key={value}
                  value={value}
                  disabled={!canApprove && ['confirmed', 'rejected', 'resolved'].includes(value)}
                >
                  {gapStatusLabel[value]}
                </option>
              ))}
            </select>
          </label>
          <label>
            分类
            <input value={gapCategory} maxLength={80} onChange={(event) => setGapCategory(event.target.value)} />
          </label>
          <label>
            差异描述
            <textarea
              value={gapDescription}
              rows={3}
              maxLength={1000}
              onChange={(event) => setGapDescription(event.target.value)}
            />
          </label>
          <label>
            建议方案
            <textarea
              value={gapRecommendation}
              rows={3}
              maxLength={1000}
              onChange={(event) => setGapRecommendation(event.target.value)}
            />
          </label>
          <label>
            负责人
            <input value={gapOwner} maxLength={120} onChange={(event) => setGapOwner(event.target.value)} />
          </label>
          <button
            type="button"
            className="secondary-button"
            disabled={knowledgePending || readOnly}
            onClick={() => void analyzeGap()}
          >
            <AlertTriangle size={15} />
            <span>分析 GAP 候选</span>
          </button>
        </section>

        {validationError && <p className="inspector-form__error">{validationError}</p>}
        <div className="inspector-form__actions">
          <button type="button" className="icon-button danger" disabled={readOnly} onClick={remove} title="删除节点">
            <Trash2 size={17} />
            <span>删除</span>
          </button>
          <button type="submit" className="command-button compact" disabled={readOnly}>
            <Save size={17} />
            <span>保存</span>
          </button>
        </div>
        </fieldset>
      </form>
    </aside>
  )
}

interface EdgeInspectorProps {
  edge: FlowEdge
  readOnly: boolean
  onClearSelection: () => void
}

function EdgeInspector({ edge, readOnly, onClearSelection }: EdgeInspectorProps) {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const [label, setLabel] = useState(edge.label ?? '')
  const [validationError, setValidationError] = useState('')
  const source = graph.nodes.find((node) => node.id === edge.source)
  const target = graph.nodes.find((node) => node.id === edge.target)

  useEffect(() => {
    setLabel(edge.label ?? '')
    setValidationError('')
  }, [edge.id, edge.label])

  const save = () => {
    if (readOnly) return
    const nextLabel = label.trim() || null
    const duplicate = graph.edges.some(
      (item) =>
        item.id !== edge.id &&
        item.source === edge.source &&
        item.target === edge.target &&
        (item.label ?? null) === nextLabel,
    )
    if (duplicate) {
      setValidationError('相同起点、终点和标签的连线已经存在。')
      return
    }
    commitGraph({
      ...graph,
      version: graph.version + 1,
      edges: graph.edges.map((item) =>
        item.id === edge.id ? { ...item, label: nextLabel } : item,
      ),
    })
    setValidationError('')
  }

  const remove = () => {
    if (readOnly) return
    commitGraph({
      ...graph,
      version: graph.version + 1,
      edges: graph.edges.filter((item) => item.id !== edge.id),
    })
    onClearSelection()
  }

  return (
    <aside className="inspector" aria-label="连线属性">
      <div className="inspector__heading">
        <span>连线属性</span>
        <small>{edge.id}</small>
      </div>
      <dl className="edge-inspector__summary">
        <div>
          <dt>起点</dt>
          <dd>{source?.label ?? edge.source}</dd>
          <code>{edge.source}</code>
        </div>
        <div>
          <dt>终点</dt>
          <dd>{target?.label ?? edge.target}</dd>
          <code>{edge.target}</code>
        </div>
        {readOnly && (
          <div>
            <dt>条件标签</dt>
            <dd>{edge.label || '无'}</dd>
          </div>
        )}
      </dl>
      {!readOnly && (
        <form
          className="inspector-form"
          onSubmit={(event) => {
            event.preventDefault()
            save()
          }}
        >
          <label>
            条件标签
            <input
              value={label}
              maxLength={200}
              placeholder="例如：通过"
              onChange={(event) => setLabel(event.target.value)}
            />
          </label>
          {validationError && <p className="inspector-form__error">{validationError}</p>}
          <div className="inspector-form__actions">
            <button type="button" className="icon-button danger" onClick={remove} title="删除连线">
              <Trash2 size={17} />
              <span>删除</span>
            </button>
            <button type="submit" className="command-button compact">
              <Save size={17} />
              <span>保存</span>
            </button>
          </div>
        </form>
      )}
    </aside>
  )
}

function SapContextManager({ readOnly }: { readOnly: boolean }) {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const [module, setModule] = useState(graph.module)
  const [scope, setScope] = useState(graph.process_scope)
  const [edition, setEdition] = useState(graph.sap_context.edition)
  const [release, setRelease] = useState(graph.sap_context.release)
  const [deployment, setDeployment] = useState(graph.sap_context.deployment)
  const [country, setCountry] = useState(graph.sap_context.country)

  useEffect(() => {
    setModule(graph.module)
    setScope(graph.process_scope)
    setEdition(graph.sap_context.edition)
    setRelease(graph.sap_context.release)
    setDeployment(graph.sap_context.deployment)
    setCountry(graph.sap_context.country)
  }, [graph.graph_id])

  const save = () => {
    if (readOnly) return
    commitGraph({
      ...graph,
      version: graph.version + 1,
      module: module.trim().toUpperCase() || 'MM',
      process_scope: scope.trim() || 'P2P',
      sap_context: {
        edition: edition.trim() || 'S/4HANA',
        release: release.trim() || '2023',
        deployment: deployment.trim() || 'private_cloud',
        country: country.trim() || 'CN',
      },
    })
  }

  return (
    <section className="inspector-form__section inspector-form__section--overview" aria-label="SAP 环境">
      <div className="inspector-form__section-heading">SAP 环境</div>
      <label>
        模块
        <input disabled={readOnly} value={module} maxLength={20} onChange={(event) => setModule(event.target.value)} />
      </label>
      <label>
        流程范围
        <input disabled={readOnly} value={scope} maxLength={30} onChange={(event) => setScope(event.target.value)} />
      </label>
      <label>
        Edition
        <input disabled={readOnly} value={edition} maxLength={50} onChange={(event) => setEdition(event.target.value)} />
      </label>
      <label>
        Release
        <input disabled={readOnly} value={release} maxLength={30} onChange={(event) => setRelease(event.target.value)} />
      </label>
      <label>
        部署方式
        <input disabled={readOnly} value={deployment} maxLength={30} onChange={(event) => setDeployment(event.target.value)} />
      </label>
      <label>
        国家/地区
        <input disabled={readOnly} value={country} maxLength={20} onChange={(event) => setCountry(event.target.value)} />
      </label>
      <button type="button" className="command-button compact inspector-form__save-context" disabled={readOnly} onClick={save}>
        <Save size={16} />
        <span>保存环境</span>
      </button>
    </section>
  )
}

function EvidenceSummary({ sap }: { sap: SapMetadata }) {
  const refs = [
    ...sap.tcodes.map((item) => ({ label: `T-Code ${item.code}`, status: item.status, evidence: item.evidence_ref })),
    ...sap.fiori_apps.map((item) => ({ label: `Fiori ${item.name}`, status: item.status, evidence: item.evidence_ref })),
    ...sap.configuration_points.map((item) => ({ label: item.label, status: item.status, evidence: item.evidence_ref })),
  ]
  return (
    <div className="inspector-evidence" aria-label="SAP 元数据状态">
      {refs.length === 0 ? (
        <span>尚无 SAP 证据</span>
      ) : (
        refs.map((item) => (
          <div key={`${item.label}-${item.evidence ?? 'none'}`} className="inspector-evidence__item">
            <span>{item.label}</span>
            <small>{metadataStatusLabel[item.status]}</small>
            {item.evidence && <code>{item.evidence}</code>}
          </div>
        ))
      )}
    </div>
  )
}

function KnowledgeEvidenceList({ evidence }: { evidence: KnowledgeEvidence[] }) {
  return (
    <div className="knowledge-results" aria-label="知识检索结果">
      {evidence.map((item) => (
        <article key={item.evidence_ref}>
          <div>
            <strong>{item.title}</strong>
            <span>{item.section}</span>
          </div>
          <p>{item.excerpt}</p>
          <code>{item.evidence_ref}</code>
        </article>
      ))}
    </div>
  )
}

const laneColors = ['#52796f', '#5b7394', '#a36f3f', '#7b668f', '#547f86']

function LaneManager({ readOnly }: { readOnly: boolean }) {
  const graph = useFlowStore((state) => state.graph)
  const commitGraph = useFlowStore((state) => state.commitGraph)

  const updateLane = (id: string, changes: Partial<Pick<Swimlane, 'label' | 'color'>>) => {
    if (readOnly) return
    commitGraph(
      applyLayout({
        ...graph,
        version: graph.version + 1,
        lanes: graph.lanes.map((lane) => (lane.id === id ? { ...lane, ...changes } : lane)),
      }),
    )
  }

  const removeLane = (lane: Swimlane) => {
    if (readOnly) return
    const assigned = graph.nodes.filter((node) => node.lane_id === lane.id).length
    if (assigned > 0 && !window.confirm(`“${lane.label}”中有 ${assigned} 个节点，删除后这些节点将变为未分配。`)) {
      return
    }
    commitGraph(
      applyLayout({
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
          disabled={readOnly || graph.lanes.length >= 20}
          onClick={() => {
            if (readOnly) return
            const number = graph.lanes.length + 1
            commitGraph(
              applyLayout({
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
              readOnly={readOnly}
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
  readOnly,
  onUpdate,
  onRemove,
}: {
  lane: Swimlane
  readOnly: boolean
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
        disabled={readOnly}
        onChange={(event) => onUpdate({ color: event.target.value })}
      />
      <input
        className="lane-editor__name"
        value={label}
        maxLength={80}
        aria-label="泳道名称"
        disabled={readOnly}
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
        disabled={readOnly}
        onClick={onRemove}
      >
        <Trash2 size={15} />
      </button>
    </div>
  )
}

function buildSapMetadata(
  existing: SapMetadata,
  values: {
    stepType: SapStepType | null
    tcodeText: string
    fioriText: string
    rolesText: string
    configurationText: string
    bestPracticeText: string
    gap: SapMetadata['gap']
  },
): SapMetadata {
  const tCodes = splitValues(values.tcodeText)
  const existingCodes = new Map(existing.tcodes.map((item) => [item.code, item]))
  const tcodes: TCodeReference[] = tCodes.map((code) =>
    existingCodes.get(code) ?? {
      code,
      status: 'pending_confirmation',
      evidence_ref: null,
    },
  )

  const fioriApps = values.fioriText
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [appId, ...nameParts] = line.split('|').map((part) => part.trim())
      const appName = nameParts.join(' | ') || appId
      const existingApp = existing.fiori_apps.find((item) => item.name === appName || item.app_id === appId)
      return (
        existingApp ?? {
          app_id: nameParts.length ? appId || null : null,
          name: appName,
          status: 'pending_confirmation' as const,
          evidence_ref: null,
        }
      )
    })

  const configurationPoints: ConfigurationPoint[] = splitLines(values.configurationText).map((label) =>
    existing.configuration_points.find((item) => item.label === label) ?? {
      label,
      status: 'pending_confirmation',
      evidence_ref: null,
    },
  )

  const bestPracticeRefs: BestPracticeReference[] = splitLines(values.bestPracticeText)
    .map((line) => {
      const [scopeItem, ...stepParts] = line.split('|').map((part) => part.trim())
      const step = stepParts.join(' | ')
      return scopeItem && step
        ? existing.best_practice_refs.find((item) => item.scope_item === scopeItem && item.step === step) ?? {
            scope_item: scopeItem,
            step,
            evidence_ref: null,
          }
        : null
    })
    .filter((item): item is BestPracticeReference => item !== null)

  return {
    ...existing,
    step_type: values.stepType,
    tcodes,
    fiori_apps: fioriApps,
    roles: splitValues(values.rolesText),
    configuration_points: configurationPoints,
    best_practice_refs: bestPracticeRefs,
    gap: values.gap,
  }
}

function splitValues(value: string): string[] {
  return value
    .split(/[\n,，、;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}
