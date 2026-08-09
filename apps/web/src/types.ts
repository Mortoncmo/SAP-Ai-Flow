export type NodeType = 'start' | 'end' | 'task' | 'decision' | 'subprocess'
export type Direction = 'TB' | 'LR'
export type SapStepType = 'transaction' | 'approval' | 'validation' | 'manual' | 'integration'
export type MetadataStatus = 'suggested' | 'pending_confirmation' | 'verified'
export type GapStatus = 'none' | 'candidate' | 'confirmed' | 'rejected' | 'resolved'
export type ProjectRole = 'viewer' | 'editor' | 'consultant_approver' | 'project_admin'

export const nodeIconKeys = [
  'user',
  'building',
  'shield-check',
  'file-text',
  'package',
  'truck',
  'circle-dollar-sign',
  'clipboard-check',
] as const
export type NodeIcon = (typeof nodeIconKeys)[number]

export const sapStepTypeKeys = [
  'transaction',
  'approval',
  'validation',
  'manual',
  'integration',
] as const

export const metadataStatusKeys = ['suggested', 'pending_confirmation', 'verified'] as const

export const gapStatusKeys = ['none', 'candidate', 'confirmed', 'rejected', 'resolved'] as const

export interface Position {
  x: number
  y: number
}

export interface SapContext {
  edition: string
  release: string
  deployment: string
  country: string
}

export interface TCodeReference {
  code: string
  status: MetadataStatus
  evidence_ref: string | null
}

export interface FioriAppReference {
  app_id: string | null
  name: string
  status: MetadataStatus
  evidence_ref: string | null
}

export interface ConfigurationPoint {
  label: string
  status: MetadataStatus
  evidence_ref: string | null
}

export interface BestPracticeReference {
  scope_item: string
  step: string
  evidence_ref: string | null
}

export interface GapAssessment {
  status: GapStatus
  category: string | null
  description: string | null
  recommendation: string | null
  confidence: number | null
  evidence_refs: string[]
  owner: string | null
}

export interface SapMetadata {
  step_type: SapStepType | null
  tcodes: TCodeReference[]
  fiori_apps: FioriAppReference[]
  roles: string[]
  configuration_points: ConfigurationPoint[]
  best_practice_refs: BestPracticeReference[]
  gap: GapAssessment
}

export interface FlowNode {
  id: string
  type: NodeType
  label: string
  description: string | null
  icon: NodeIcon | null
  lane_id: string | null
  sap: SapMetadata
}

export interface Swimlane {
  id: string
  label: string
  color: string
}

export interface FlowEdge {
  id: string
  source: string
  target: string
  label: string | null
}

export interface GraphDocument {
  schema_version: '2.0'
  graph_id: string
  version: number
  title: string
  module: string
  process_scope: string
  sap_context: SapContext
  direction: Direction
  nodes: FlowNode[]
  edges: FlowEdge[]
  lanes: Swimlane[]
  layout: Record<string, Position>
}

export interface ModifyResponse {
  request_id: string
  base_version: number
  graph: GraphDocument
  applied_patch: {
    change_summary: string
    operations: unknown[]
  }
  warnings: string[]
  metrics: {
    provider: string
    model: string
    attempts: number
    latency_ms: number
  }
}

export interface KnowledgeEvidence {
  evidence_ref: string
  source_id: string
  title: string
  section: string
  excerpt: string
  source_path: string
  source_url: string | null
  sap_release: string | null
  review_status: string
  score: number
}

export interface KnowledgeSearchResponse {
  status: 'results' | 'insufficient_evidence'
  evidence: KnowledgeEvidence[]
  warnings: string[]
}

export interface GapAnalyzeResponse {
  outcome: 'candidate' | 'no_candidate' | 'insufficient_evidence'
  gap: GapAssessment | null
  evidence: KnowledgeEvidence[]
  warnings: string[]
}

export interface ProjectSummary {
  id: string
  name: string
  customer_name: string | null
  sap_context: SapContext
  external_model_enabled: boolean
  current_role: 'viewer' | 'editor' | 'consultant_approver' | 'project_admin'
  created_at: string
  updated_at: string
}

export interface ProjectMember {
  project_id: string
  user_id: string
  role: ProjectRole
  created_by: string
  updated_by: string
  created_at: string
  updated_at: string
}

export interface ProcessSummary {
  id: string
  project_id: string
  name: string
  module: string
  process_scope: string
  status: string
  current_revision: number
  latest_release_no: number | null
  created_at: string
  updated_at: string
}

export interface ProcessDetail extends ProcessSummary {
  graph: GraphDocument
}

export interface PersistedModifyResponse {
  request_id: string
  base_revision: number
  result_revision: number
  graph: GraphDocument
  applied_patch: ModifyResponse['applied_patch']
  evidence: KnowledgeEvidence[]
  warnings: string[]
  metrics: ModifyResponse['metrics']
}

export interface ManualSaveResponse {
  request_id: string
  base_revision: number
  result_revision: number
  graph: GraphDocument
}

export interface RevisionSummary {
  revision_no: number
  release_no: number | null
  lifecycle_state: string
  schema_version: string
  created_by: string
  created_at: string
}

export interface RevisionDetail extends RevisionSummary {
  process_id: string
  graph: GraphDocument
}

export interface ReleaseResponse {
  process_id: string
  revision_no: number
  release_no: number
  lifecycle_state: string
}

export interface GapDecisionResponse {
  process_id: string
  node_id: string
  revision_no: number
  from_status: string
  to_status: string
  comment: string
  decided_by: string
  decided_at: string
  graph: GraphDocument
}
