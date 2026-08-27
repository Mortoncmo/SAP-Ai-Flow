import { nodeIconKeys } from './types'
import type {
  BestPracticeReference,
  ConfigurationPoint,
  FlowNode,
  GapAssessment,
  GraphDocument,
  MetadataStatus,
  NodeIcon,
  NodeType,
  SapContext,
  SapMetadata,
  SapStepType,
  Swimlane,
  TCodeReference,
} from './types'

const DEFAULT_CONTEXT: SapContext = {
  edition: 'S/4HANA',
  release: '2023',
  deployment: 'private_cloud',
  country: 'CN',
}

const nodeTypes: NodeType[] = ['start', 'end', 'task', 'decision', 'subprocess']
const sapStepTypes: SapStepType[] = [
  'transaction',
  'approval',
  'validation',
  'manual',
  'integration',
]
const metadataStatuses: MetadataStatus[] = ['suggested', 'pending_confirmation', 'verified']
const gapStatuses: GapAssessment['status'][] = [
  'none',
  'candidate',
  'confirmed',
  'rejected',
  'resolved',
]

export function createId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`
}

export function emptySapMetadata(): SapMetadata {
  return {
    step_type: null,
    tcodes: [],
    fiori_apps: [],
    roles: [],
    configuration_points: [],
    best_practice_refs: [],
    gap: {
      status: 'none',
      category: null,
      description: null,
      recommendation: null,
      confidence: null,
      evidence_refs: [],
      owner: null,
    },
  }
}

export function createEmptyGraph(): GraphDocument {
  return {
    schema_version: '2.0',
    graph_id: createId('graph'),
    version: 0,
    title: '未命名流程',
    module: 'MM',
    process_scope: 'P2P',
    sap_context: { ...DEFAULT_CONTEXT },
    direction: 'TB',
    nodes: [],
    edges: [],
    lanes: [],
    layout: {},
  }
}

export function createSampleGraph(): GraphDocument {
  const pendingTCode = (code: string): TCodeReference => ({
    code,
    status: 'pending_confirmation',
    evidence_ref: null,
  })
  const j45 = (step: string): BestPracticeReference => ({
    scope_item: 'J45',
    step,
    evidence_ref: null,
  })
  const sap = (stepType: SapStepType, code: string, role: string, step: string): SapMetadata => ({
    ...emptySapMetadata(),
    step_type: stepType,
    tcodes: [pendingTCode(code)],
    roles: [role],
    best_practice_refs: [j45(step)],
  })

  return {
    schema_version: '2.0',
    graph_id: 'graph_mm_p2p_demo',
    version: 0,
    title: 'MM 直接物料采购流程',
    module: 'MM',
    process_scope: 'P2P',
    sap_context: { ...DEFAULT_CONTEXT },
    direction: 'LR',
    nodes: [
      { id: 'start', type: 'start', label: '开始', description: null, icon: null, lane_id: 'lane_requester', sap: emptySapMetadata() },
      {
        id: 'pr',
        type: 'task',
        label: '创建采购申请',
        description: '需求部门提出直接物料采购需求',
        icon: 'file-text',
        lane_id: 'lane_requester',
        sap: sap('transaction', 'ME51N', 'Requester', 'Create Purchase Requisition'),
      },
      {
        id: 'approval',
        type: 'task',
        label: '采购申请审批',
        description: '根据审批策略确认采购申请',
        icon: 'clipboard-check',
        lane_id: 'lane_approval',
        sap: sap('approval', 'ME54N', 'Approver', 'Approve Purchase Requisition'),
      },
      {
        id: 'po',
        type: 'task',
        label: '创建采购订单',
        description: '分配供货源并生成采购订单',
        icon: 'file-text',
        lane_id: 'lane_buyer',
        sap: sap('transaction', 'ME21N', 'Purchaser', 'Create Purchase Order'),
      },
      {
        id: 'gr',
        type: 'task',
        label: '货物接收',
        description: '仓库接收物料并登记入库',
        icon: 'package',
        lane_id: 'lane_warehouse',
        sap: sap('transaction', 'MIGO', 'Warehouse Clerk', 'Post Goods Receipt'),
      },
      {
        id: 'ir',
        type: 'task',
        label: '发票校验',
        description: '校验供应商发票并匹配采购订单',
        icon: 'file-text',
        lane_id: 'lane_finance',
        sap: sap('validation', 'MIRO', 'Accounts Payable', 'Post Supplier Invoice'),
      },
      { id: 'end', type: 'end', label: '结束', description: null, icon: null, lane_id: 'lane_finance', sap: emptySapMetadata() },
    ],
    edges: [
      { id: 'edge_start_pr', source: 'start', target: 'pr', label: null },
      { id: 'edge_pr_approval', source: 'pr', target: 'approval', label: null },
      { id: 'edge_approval_po', source: 'approval', target: 'po', label: '通过' },
      { id: 'edge_po_gr', source: 'po', target: 'gr', label: null },
      { id: 'edge_gr_ir', source: 'gr', target: 'ir', label: null },
      { id: 'edge_ir_end', source: 'ir', target: 'end', label: null },
    ],
    lanes: [
      { id: 'lane_requester', label: '需求部门', color: '#52796f' },
      { id: 'lane_approval', label: '审批人', color: '#7b668f' },
      { id: 'lane_buyer', label: '采购部门', color: '#5b7394' },
      { id: 'lane_warehouse', label: '仓库', color: '#547f86' },
      { id: 'lane_finance', label: '财务', color: '#a36f3f' },
    ],
    layout: {},
  }
}

export function normalizeGraph(input: unknown): GraphDocument {
  if (!isRecord(input)) return createEmptyGraph()

  const graph = input
  const lanes = asArray(graph.lanes)
    .slice(0, 20)
    .map((lane, index) => normalizeLane(lane, index))
    .filter((lane): lane is Swimlane => lane !== null)
  const laneIds = new Set(lanes.map((lane) => lane.id))
  const nodes = asArray(graph.nodes)
    .slice(0, 500)
    .map((node, index) => normalizeNode(node, index, laneIds))
    .filter((node): node is FlowNode => node !== null)
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = asArray(graph.edges)
    .slice(0, 1000)
    .map((edge, index) => normalizeEdge(edge, index, nodeIds))
    .filter((edge) => edge !== null)

  return {
    schema_version: '2.0',
    graph_id: stringValue(graph.graph_id, createId('graph')),
    version: numberValue(graph.version, 0),
    title: stringValue(graph.title, '未命名流程'),
    module: stringValue(graph.module, 'MM').toUpperCase(),
    process_scope: stringValue(graph.process_scope, 'P2P'),
    sap_context: normalizeContext(graph.sap_context),
    direction: graph.direction === 'LR' ? 'LR' : 'TB',
    nodes,
    edges,
    lanes,
    layout: normalizeLayout(graph.layout, nodeIds),
  }
}

function normalizeContext(value: unknown): SapContext {
  const context = isRecord(value) ? value : {}
  return {
    edition: stringValue(context.edition, DEFAULT_CONTEXT.edition),
    release: stringValue(context.release, DEFAULT_CONTEXT.release),
    deployment: stringValue(context.deployment, DEFAULT_CONTEXT.deployment),
    country: stringValue(context.country, DEFAULT_CONTEXT.country),
  }
}

function normalizeNode(value: unknown, index: number, laneIds: Set<string>): FlowNode | null {
  if (!isRecord(value)) return null
  const id = stringValue(value.id, `node_${index + 1}`)
  const type = nodeTypes.includes(value.type as NodeType) ? (value.type as NodeType) : 'task'
  const icon = nodeIconKeys.includes(value.icon as NodeIcon) ? (value.icon as NodeIcon) : null
  const rawLaneId = stringValue(value.lane_id, '')
  return {
    id,
    type,
    label: stringValue(value.label, '新处理步骤'),
    description: nullableString(value.description),
    icon,
    lane_id: rawLaneId && laneIds.has(rawLaneId) ? rawLaneId : null,
    sap: normalizeSapMetadata(value.sap),
  }
}

function normalizeLane(value: unknown, index: number): Swimlane | null {
  if (!isRecord(value)) return null
  const id = stringValue(value.id, `lane_${index + 1}`)
  return {
    id,
    label: stringValue(value.label, `泳道 ${index + 1}`),
    color: /^#[0-9a-fA-F]{6}$/.test(stringValue(value.color, ''))
      ? String(value.color)
      : '#52796f',
  }
}

function normalizeEdge(value: unknown, index: number, nodeIds: Set<string>) {
  if (!isRecord(value)) return null
  const source = stringValue(value.source, '')
  const target = stringValue(value.target, '')
  if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target) || source === target) return null
  return {
    id: stringValue(value.id, `edge_${index + 1}`),
    source,
    target,
    label: nullableString(value.label),
  }
}

function normalizeLayout(value: unknown, nodeIds: Set<string>): Record<string, { x: number; y: number }> {
  if (!isRecord(value)) return {}
  return Object.fromEntries(
    Object.entries(value)
      .filter(([id, position]) => nodeIds.has(id) && isRecord(position))
      .map(([id, rawPosition]) => {
        const position = rawPosition as Record<string, unknown>
        return [id, { x: numberValue(position.x, 0), y: numberValue(position.y, 0) }]
      }),
  )
}

function normalizeSapMetadata(value: unknown): SapMetadata {
  const sap = isRecord(value) ? value : {}
  const stepType = sapStepTypes.includes(sap.step_type as SapStepType)
    ? (sap.step_type as SapStepType)
    : null
  const gapValue = isRecord(sap.gap) ? sap.gap : {}
  const gapStatus = gapStatuses.includes(gapValue.status as GapAssessment['status'])
    ? (gapValue.status as GapAssessment['status'])
    : 'none'
  return {
    step_type: stepType,
    tcodes: asArray(sap.tcodes)
      .map((item) => normalizeTCode(item))
      .filter((item): item is TCodeReference => item !== null),
    fiori_apps: asArray(sap.fiori_apps)
      .map((item) => normalizeFioriApp(item))
      .filter((item): item is SapMetadata['fiori_apps'][number] => item !== null),
    roles: asArray(sap.roles).map((item) => String(item).trim()).filter(Boolean).slice(0, 20),
    configuration_points: asArray(sap.configuration_points)
      .map((item) => normalizeConfigurationPoint(item))
      .filter((item): item is ConfigurationPoint => item !== null),
    best_practice_refs: asArray(sap.best_practice_refs)
      .map((item) => normalizeBestPracticeReference(item))
      .filter((item): item is BestPracticeReference => item !== null),
    gap: {
      status: gapStatus,
      category: nullableString(gapValue.category),
      description: nullableString(gapValue.description),
      recommendation: nullableString(gapValue.recommendation),
      confidence: gapValue.confidence === null ? null : numberOrNull(gapValue.confidence),
      evidence_refs: asArray(gapValue.evidence_refs)
        .map((item) => String(item).trim())
        .filter(Boolean)
        .slice(0, 20),
      owner: nullableString(gapValue.owner),
    },
  }
}

function normalizeTCode(value: unknown): TCodeReference | null {
  if (typeof value === 'string' && value.trim()) {
    return { code: value.trim(), status: 'pending_confirmation', evidence_ref: null }
  }
  if (!isRecord(value)) return null
  const code = stringValue(value.code, '').trim()
  if (!code) return null
  return {
    code,
    status: normalizeMetadataStatus(value.status),
    evidence_ref: nullableString(value.evidence_ref),
  }
}

function normalizeFioriApp(value: unknown) {
  if (!isRecord(value)) return null
  const name = stringValue(value.name, '').trim()
  if (!name) return null
  return {
    app_id: nullableString(value.app_id),
    name,
    status: normalizeMetadataStatus(value.status),
    evidence_ref: nullableString(value.evidence_ref),
  }
}

function normalizeConfigurationPoint(value: unknown): ConfigurationPoint | null {
  const label = typeof value === 'string' ? value.trim() : isRecord(value) ? stringValue(value.label, '').trim() : ''
  if (!label) return null
  return {
    label,
    status: isRecord(value) ? normalizeMetadataStatus(value.status) : 'pending_confirmation',
    evidence_ref: isRecord(value) ? nullableString(value.evidence_ref) : null,
  }
}

function normalizeBestPracticeReference(value: unknown): BestPracticeReference | null {
  if (!isRecord(value)) return null
  const scopeItem = stringValue(value.scope_item, '').trim()
  const step = stringValue(value.step, '').trim()
  if (!scopeItem || !step) return null
  return { scope_item: scopeItem, step, evidence_ref: nullableString(value.evidence_ref) }
}

function normalizeMetadataStatus(value: unknown): MetadataStatus {
  return metadataStatuses.includes(value as MetadataStatus)
    ? (value as MetadataStatus)
    : 'pending_confirmation'
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function nullableString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function numberValue(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function numberOrNull(value: unknown): number | null {
  const number = numberValue(value, Number.NaN)
  return Number.isFinite(number) ? Math.min(1, Math.max(0, number)) : null
}
