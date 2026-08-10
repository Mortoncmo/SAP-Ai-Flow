import type {
  GapAnalyzeResponse,
  GraphDocument,
  KnowledgeSearchResponse,
  ModifyResponse,
  ManualSaveResponse,
  PersistedModifyResponse,
  ProcessDetail,
  ProcessSummary,
  ProjectSummary,
  ReleaseResponse,
  RevisionSummary,
  RevisionDetail,
  GapDecisionResponse,
  ExportJobResponse,
  ProjectAudit,
  ProjectMember,
  ProjectRole,
} from '../types'
import { parseDownloadFilename } from '../export'
import { clearOidcSession, getAccessToken } from '../auth/oidc'

const API_ROOT = import.meta.env.VITE_API_URL ?? ''
export const API_REQUEST_TIMEOUT_MS = timeoutValue(
  import.meta.env.VITE_API_TIMEOUT_MS,
  40_000,
)
export const EXPORT_REQUEST_TIMEOUT_MS = timeoutValue(
  import.meta.env.VITE_EXPORT_TIMEOUT_MS,
  44_000,
)

export class ApiError extends Error {
  constructor(
    message: string,
    readonly code = 'UNKNOWN_ERROR',
  ) {
    super(message)
  }
}

export async function modifyFlowchart(
  graph: GraphDocument,
  instruction: string,
  signal?: AbortSignal,
): Promise<ModifyResponse> {
  const requestId = `request_${crypto.randomUUID().replaceAll('-', '')}`
  const response = await authorizedFetch(`${API_ROOT}/api/v1/flowcharts/modify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Request-ID': requestId },
    body: JSON.stringify({
      request_id: requestId,
      current_graph: graph,
      instruction,
      locale: 'zh-CN',
    }),
    signal,
  })

  const payload = await response.json()
  if (!response.ok) {
    throw new ApiError(
      payload?.error?.message ?? '流程修改失败，请稍后重试。',
      payload?.error?.code,
    )
  }
  return payload as ModifyResponse
}

export async function searchSapKnowledge(
  graph: GraphDocument,
  query: string,
  projectId?: string,
  signal?: AbortSignal,
): Promise<KnowledgeSearchResponse> {
  return postJson<KnowledgeSearchResponse>(
    projectId
      ? `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/search`
      : '/api/v1/knowledge/search',
    {
      module: graph.module,
      process_scope: graph.process_scope,
      query,
      sap_context: graph.sap_context,
      top_k: 5,
    },
    signal,
  )
}

export async function analyzeGapCandidate(
  graph: GraphDocument,
  businessRequirement: string,
  projectId?: string,
  signal?: AbortSignal,
): Promise<GapAnalyzeResponse> {
  return postJson<GapAnalyzeResponse>(
    projectId
      ? `/api/v1/projects/${encodeURIComponent(projectId)}/gaps/analyze`
      : '/api/v1/gaps/analyze',
    {
      module: graph.module,
      process_scope: graph.process_scope,
      business_requirement: businessRequirement,
      sap_context: graph.sap_context,
    },
    signal,
  )
}

export async function listProjects(signal?: AbortSignal): Promise<ProjectSummary[]> {
  return getJson<ProjectSummary[]>('/api/v1/projects', signal)
}

export async function createProject(
  name: string,
  customerName?: string,
  signal?: AbortSignal,
): Promise<ProjectSummary> {
  return postJson<ProjectSummary>(
    '/api/v1/projects',
    { name, customer_name: customerName || null },
    signal,
  )
}

export async function updateProjectSettings(
  projectId: string,
  externalModelEnabled: boolean,
  signal?: AbortSignal,
): Promise<ProjectSummary> {
  return putJson<ProjectSummary>(
    `/api/v1/projects/${encodeURIComponent(projectId)}`,
    { external_model_enabled: externalModelEnabled },
    signal,
  )
}

export async function listProjectMembers(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectMember[]> {
  return getJson<ProjectMember[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members`,
    signal,
  )
}

export async function listProjectAudits(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectAudit[]> {
  return getJson<ProjectAudit[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/audits`,
    signal,
  )
}

export async function addProjectMember(
  projectId: string,
  userId: string,
  role: ProjectRole,
  signal?: AbortSignal,
): Promise<ProjectMember> {
  return postJson<ProjectMember>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members`,
    { user_id: userId, role },
    signal,
  )
}

export async function updateProjectMember(
  projectId: string,
  userId: string,
  role: ProjectRole,
  signal?: AbortSignal,
): Promise<ProjectMember> {
  return putJson<ProjectMember>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
    { user_id: userId, role },
    signal,
  )
}

export async function removeProjectMember(
  projectId: string,
  userId: string,
  signal?: AbortSignal,
): Promise<void> {
  await requestJson(
    `/api/v1/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`,
    { method: 'DELETE', signal },
  )
}

export async function listProcesses(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProcessSummary[]> {
  return getJson<ProcessSummary[]>(`/api/v1/projects/${encodeURIComponent(projectId)}/processes`, signal)
}

export async function createProcess(
  projectId: string,
  name: string,
  signal?: AbortSignal,
): Promise<ProcessDetail> {
  return postJson<ProcessDetail>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/processes`,
    { name, module: 'MM', process_scope: 'P2P' },
    signal,
  )
}

export async function getProcess(processId: string, signal?: AbortSignal): Promise<ProcessDetail> {
  return getJson<ProcessDetail>(`/api/v1/processes/${encodeURIComponent(processId)}`, signal)
}

export async function modifyPersistedFlow(
  processId: string,
  baseRevision: number,
  instruction: string,
  signal?: AbortSignal,
): Promise<PersistedModifyResponse> {
  const requestId = createRequestId()
  return postJson<PersistedModifyResponse>(
    `/api/v1/processes/${encodeURIComponent(processId)}/modify`,
    {
      request_id: requestId,
      base_revision: baseRevision,
      instruction,
      locale: 'zh-CN',
    },
    signal,
    requestId,
  )
}

export async function savePersistedFlow(
  processId: string,
  baseRevision: number,
  graph: GraphDocument,
  summary = '保存画布修订',
  signal?: AbortSignal,
): Promise<ManualSaveResponse> {
  const requestId = createRequestId()
  return postJson<ManualSaveResponse>(
    `/api/v1/processes/${encodeURIComponent(processId)}/save`,
    {
      request_id: requestId,
      base_revision: baseRevision,
      graph: { ...graph, version: baseRevision + 1 },
      summary,
    },
    signal,
    requestId,
  )
}

export async function listRevisions(
  processId: string,
  signal?: AbortSignal,
): Promise<RevisionSummary[]> {
  return getJson<RevisionSummary[]>(`/api/v1/processes/${encodeURIComponent(processId)}/revisions`, signal)
}

export async function getRevision(
  processId: string,
  revisionNo: number,
  signal?: AbortSignal,
): Promise<RevisionDetail> {
  return getJson<RevisionDetail>(
    `/api/v1/processes/${encodeURIComponent(processId)}/revisions/${revisionNo}`,
    signal,
  )
}

export async function releaseProcess(
  processId: string,
  baseRevision: number,
  signal?: AbortSignal,
): Promise<ReleaseResponse> {
  return postJson<ReleaseResponse>(
    `/api/v1/processes/${encodeURIComponent(processId)}/releases`,
    { base_revision: baseRevision },
    signal,
  )
}

export async function createDraftFromRelease(
  processId: string,
  sourceRevision: number,
  signal?: AbortSignal,
): Promise<RevisionDetail> {
  return postJson<RevisionDetail>(
    `/api/v1/processes/${encodeURIComponent(processId)}/drafts`,
    { source_revision: sourceRevision },
    signal,
  )
}

export async function decideGap(
  processId: string,
  nodeId: string,
  baseRevision: number,
  toStatus: 'confirmed' | 'rejected' | 'resolved',
  comment: string,
  signal?: AbortSignal,
): Promise<GapDecisionResponse> {
  return postJson<GapDecisionResponse>(
    `/api/v1/processes/${encodeURIComponent(processId)}/gaps/${encodeURIComponent(nodeId)}/decisions`,
    { base_revision: baseRevision, to_status: toStatus, comment },
    signal,
  )
}

export async function exportBlueprint(
  processId: string,
  revisionNo: number,
  format: 'markdown' | 'docx',
  signal?: AbortSignal,
): Promise<{ blob: Blob; filename: string }> {
  const route = `/api/v1/processes/${encodeURIComponent(processId)}/exports/jobs`
  const deadline = Date.now() + EXPORT_REQUEST_TIMEOUT_MS
  const created = await authorizedFetch(`${API_ROOT}${route}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revision_no: revisionNo, format }),
    signal,
  }, remainingExportTime(deadline))
  const createdPayload = await created.json()
  if (!created.ok) {
    throw new ApiError(
      createdPayload?.error?.message ?? '蓝图导出失败。',
      createdPayload?.error?.code,
    )
  }
  let job = createdPayload as ExportJobResponse
  while (job.status === 'pending' || job.status === 'running') {
    await waitForExportPoll(signal, deadline)
    const statusResponse = await authorizedFetch(
      `${API_ROOT}${route}/${encodeURIComponent(job.export_id)}`,
      { signal },
      remainingExportTime(deadline),
    )
    const statusPayload = await statusResponse.json()
    if (!statusResponse.ok) {
      throw new ApiError(
        statusPayload?.error?.message ?? '导出状态查询失败。',
        statusPayload?.error?.code,
      )
    }
    job = statusPayload as ExportJobResponse
  }
  if (job.status !== 'completed' || !job.download_url) {
    throw new ApiError(
      job.error_message ?? (job.status === 'expired' ? '导出文件已过期，请重新生成。' : '蓝图导出失败。'),
      job.error_code ?? (job.status === 'expired' ? 'EXPORT_EXPIRED' : 'EXPORT_RENDER_FAILED'),
    )
  }
  const response = await authorizedFetch(
    `${API_ROOT}${job.download_url}`,
    { signal },
    remainingExportTime(deadline),
  )
  if (!response.ok) {
    const payload = await response.json()
    throw new ApiError(payload?.error?.message ?? '蓝图下载失败。', payload?.error?.code)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const filename = parseDownloadFilename(
    disposition,
    job.filename ?? `SAP-Blueprint.${format === 'docx' ? 'docx' : 'md'}`,
  )
  return { blob: await response.blob(), filename }
}

function remainingExportTime(deadline: number): number {
  const remaining = deadline - Date.now()
  if (remaining <= 0) {
    throw new ApiError('蓝图导出超时，请稍后查询或重新生成。', 'REQUEST_TIMEOUT')
  }
  return Math.max(1, remaining)
}

function waitForExportPoll(signal: AbortSignal | undefined, deadline: number): Promise<void> {
  remainingExportTime(deadline)
  return new Promise((resolve, reject) => {
    let timeoutId: ReturnType<typeof globalThis.setTimeout> | undefined
    const abort = () => {
      if (timeoutId !== undefined) globalThis.clearTimeout(timeoutId)
      reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    }
    if (signal?.aborted) {
      abort()
      return
    }
    timeoutId = globalThis.setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, 250)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

async function postJson<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
  requestId?: string,
): Promise<T> {
  return requestJson<T>(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(requestId ? { 'X-Request-ID': requestId } : {}),
    },
    body: JSON.stringify(body),
    signal,
  })
}

async function putJson<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return requestJson<T>(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

async function requestJson<T>(path: string, init: RequestInit): Promise<T> {
  const response = await authorizedFetch(`${API_ROOT}${path}`, init)
  if (response.status === 204) return undefined as T
  const payload = await response.json()
  if (!response.ok) {
    throw new ApiError(payload?.error?.message ?? '请求失败，请稍后重试。', payload?.error?.code)
  }
  return payload as T
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await authorizedFetch(`${API_ROOT}${path}`, { signal })
  const payload = await response.json()
  if (!response.ok) {
    throw new ApiError(payload?.error?.message ?? '请求失败，请稍后重试。', payload?.error?.code)
  }
  return payload as T
}

async function authorizedFetch(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs = API_REQUEST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const externalSignal = init.signal
  let timedOut = false
  const forwardAbort = () => controller.abort(externalSignal?.reason)
  if (externalSignal?.aborted) {
    forwardAbort()
  } else {
    externalSignal?.addEventListener('abort', forwardAbort, { once: true })
  }
  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  try {
    const accessToken = await getAccessToken()
    const headers = new Headers(init.headers)
    if (!headers.has('X-Request-ID')) {
      headers.set('X-Request-ID', `web_${crypto.randomUUID().replaceAll('-', '')}`)
    }
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
    const response = await fetch(input, { ...init, headers, signal: controller.signal })
    if (response.status === 401) await clearOidcSession().catch(() => undefined)
    return response
  } catch (caught) {
    if (timedOut) {
      throw new ApiError('请求超时，当前数据未改变，请重试。', 'REQUEST_TIMEOUT')
    }
    throw caught
  } finally {
    globalThis.clearTimeout(timeoutId)
    externalSignal?.removeEventListener('abort', forwardAbort)
  }
}

function createRequestId(): string {
  return `web_${crypto.randomUUID().replaceAll('-', '')}`
}

function timeoutValue(raw: string | undefined, fallback: number): number {
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed >= 1_000 && parsed <= 120_000
    ? Math.floor(parsed)
    : fallback
}
