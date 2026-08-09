import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  BackgroundVariant,
  Connection,
  Controls,
  Edge,
  MarkerType,
  MiniMap,
  Node,
  ReactFlow,
  ReactFlowProvider,
  useNodesState,
  useReactFlow,
  getViewportForBounds,
} from '@xyflow/react'
import { toPng, toSvg } from 'html-to-image'
import {
  Bot,
  FolderPlus,
  FileCode2,
  FileDown,
  FileJson,
  FilePlus2,
  FileText,
  GitBranchPlus,
  ImageDown,
  LayoutDashboard,
  LoaderCircle,
  LogIn,
  LogOut,
  CopyPlus,
  PanelRight,
  Redo2,
  Save,
  Send,
  SendToBack,
  Trash2,
  Undo2,
  Upload,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import {
  ApiError,
  createProcess,
  createProject,
  createDraftFromRelease,
  exportBlueprint,
  getProcess,
  addProjectMember,
  listProcesses,
  listProjectMembers,
  listProjects,
  listRevisions,
  getRevision,
  modifyFlowchart,
  modifyPersistedFlow,
  removeProjectMember,
  releaseProcess,
  savePersistedFlow,
  updateProjectMember,
  updateProjectSettings,
} from './api/client'
import {
  initializeOidcAuth,
  startOidcSignIn,
  startOidcSignOut,
  type AuthSession,
} from './auth/oidc'
import { Inspector } from './components/Inspector'
import { createEmptyGraph, createId, normalizeGraph } from './data'
import { buildExportFilename, downloadBlob, downloadUrl } from './export'
import { BusinessNode, BusinessNodeData, BusinessNodeModel } from './flow/BusinessNode'
import { LaneNode, LaneNodeData, LaneNodeModel } from './flow/LaneNode'
import { laneFrames, laneIdAtPosition, layoutGraph, nodeDimensions } from './flow/layout'
import { useFlowStore } from './stores/flowStore'
import type {
  GraphDocument,
  ProcessSummary,
  ProjectMember,
  ProjectRole,
  ProjectSummary,
  RevisionSummary,
} from './types'

type VisualNode = BusinessNodeModel | LaneNodeModel

const nodeTypes = { business: BusinessNode, lane: LaneNode }
const projectRoleRank = {
  viewer: 0,
  editor: 1,
  consultant_approver: 2,
  project_admin: 3,
} as const

const projectRoleLabels: Record<ProjectRole, string> = {
  viewer: '查看者',
  editor: '编辑者',
  consultant_approver: '顾问审批者',
  project_admin: '项目管理员',
}

interface FlowWorkspaceProps {
  authSession: AuthSession
  authActionPending: boolean
  authError: string
  onSignIn: () => Promise<void>
  onSignOut: () => Promise<void>
}

function FlowWorkspace({
  authSession,
  authActionPending,
  authError,
  onSignIn,
  onSignOut,
}: FlowWorkspaceProps) {
  const graph = useFlowStore((state) => state.graph)
  const past = useFlowStore((state) => state.past)
  const future = useFlowStore((state) => state.future)
  const commitGraph = useFlowStore((state) => state.commitGraph)
  const undo = useFlowStore((state) => state.undo)
  const redo = useFlowStore((state) => state.redo)
  const reset = useFlowStore((state) => state.reset)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [instruction, setInstruction] = useState('在采购申请后增加供应商确认')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('本地规则引擎已就绪')
  const [error, setError] = useState('')
  const [inspectorOpen, setInspectorOpen] = useState(true)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [processes, setProcesses] = useState<ProcessSummary[]>([])
  const [projectId, setProjectId] = useState('')
  const [processId, setProcessId] = useState('')
  const [baseRevision, setBaseRevision] = useState<number | null>(null)
  const [releaseNo, setReleaseNo] = useState<number | null>(null)
  const [revisions, setRevisions] = useState<RevisionSummary[]>([])
  const [projectPending, setProjectPending] = useState(false)
  const [memberDialogOpen, setMemberDialogOpen] = useState(false)
  const [members, setMembers] = useState<ProjectMember[]>([])
  const [memberPending, setMemberPending] = useState(false)
  const [policyPending, setPolicyPending] = useState(false)
  const [memberError, setMemberError] = useState('')
  const [newMemberUserId, setNewMemberUserId] = useState('')
  const [newMemberRole, setNewMemberRole] = useState<ProjectRole>('viewer')
  const [selectedRevision, setSelectedRevision] = useState('')
  const [readOnlyRevision, setReadOnlyRevision] = useState<number | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const importRef = useRef<HTMLInputElement>(null)
  const { fitView, getNodes, getNodesBounds } = useReactFlow()
  const currentProject = projects.find((project) => project.id === projectId)
  const currentProjectRole = currentProject?.current_role
  const canEditProject =
    !projectId || (currentProjectRole !== undefined && projectRoleRank[currentProjectRole] >= 1)
  const canApproveProject =
    !projectId || (currentProjectRole !== undefined && projectRoleRank[currentProjectRole] >= 2)
  const canManageMembers = currentProjectRole === 'project_admin'
  const requiresSignIn = authSession.configured && !authSession.authenticated
  const projectAdminCount = members.filter((member) => member.role === 'project_admin').length
  const isReadOnly =
    readOnlyRevision !== null || releaseNo !== null || (Boolean(projectId) && !canEditProject)

  const fitCanvas = useCallback(() => {
    window.setTimeout(() => {
      void fitView({
        padding: 0.18,
        minZoom: window.innerWidth <= 720 ? 0.55 : 0.25,
        maxZoom: 1.15,
        duration: 280,
      })
    }, 40)
  }, [fitView])

  useEffect(() => {
    const handleResize = () => fitCanvas()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [fitCanvas])

  useEffect(() => {
    if (requiresSignIn) return
    let cancelled = false
    void listProjects()
      .then((items) => {
        if (!cancelled) setProjects(items)
      })
      .catch(() => {
        // The canvas remains usable in local-only mode when the API is offline.
      })
    return () => {
      cancelled = true
    }
  }, [requiresSignIn])

  useEffect(() => {
    if (!memberDialogOpen) return
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMemberDialogOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [memberDialogOpen])

  useEffect(() => {
    setMemberDialogOpen(false)
    setMembers([])
    setMemberError('')
    setNewMemberUserId('')
    if (!projectId || currentProjectRole !== 'project_admin') return
    let cancelled = false
    void listProjectMembers(projectId)
      .then((items) => {
        if (!cancelled) setMembers(items)
      })
      .catch((caught) => {
        if (!cancelled) setMemberError(caught instanceof Error ? caught.message : '读取项目成员失败')
      })
    return () => {
      cancelled = true
    }
  }, [currentProjectRole, projectId])

  const loadProcess = useCallback(
    async (nextProcessId: string) => {
      if (!nextProcessId) {
        setProcessId('')
        setBaseRevision(null)
        setReleaseNo(null)
        setRevisions([])
        setSelectedRevision('')
        setReadOnlyRevision(null)
        return
      }
      setProjectPending(true)
      try {
        const [detail, history] = await Promise.all([getProcess(nextProcessId), listRevisions(nextProcessId)])
        reset(layoutGraph(normalizeGraph(detail.graph)))
        setProcessId(detail.id)
        setBaseRevision(detail.current_revision)
        setRevisions(history)
        setSelectedRevision(String(detail.current_revision))
        setReadOnlyRevision(null)
        setReleaseNo(history.find((item) => item.revision_no === detail.current_revision)?.release_no ?? null)
        setSelectedNodeId(null)
        setSelectedEdgeId(null)
        setMessage(`已打开 ${detail.name} · 修订 ${detail.current_revision}`)
        setError('')
        fitCanvas()
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : '打开流程失败')
      } finally {
        setProjectPending(false)
      }
    },
    [fitCanvas, reset],
  )

  const handleProjectChange = async (nextProjectId: string) => {
    setProjectId(nextProjectId)
    setProcessId('')
    setBaseRevision(null)
    setReleaseNo(null)
        setRevisions([])
        setSelectedRevision('')
    if (!nextProjectId) {
      setProcesses([])
      setMessage('本地演示模式')
      return
    }
    setProjectPending(true)
    try {
      const items = await listProcesses(nextProjectId)
      setProcesses(items)
      setMessage(items.length ? '请选择一个流程' : '项目暂无流程，请创建流程')
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '读取流程失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleCreateProject = async () => {
    const name = window.prompt('项目名称')?.trim()
    if (!name) return
    setProjectPending(true)
    try {
      const project = await createProject(name)
      setProjects((items) => [...items, project])
      await handleProjectChange(project.id)
      setMessage(`已创建项目：${project.name}`)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建项目失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleOpenMemberDialog = async () => {
    if (!projectId || !canManageMembers) return
    setMemberDialogOpen(true)
    setMemberError('')
    setMemberPending(true)
    try {
      setMembers(await listProjectMembers(projectId))
    } catch (caught) {
      setMemberError(caught instanceof Error ? caught.message : '读取项目成员失败')
    } finally {
      setMemberPending(false)
    }
  }

  const handleAddMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const userId = newMemberUserId.trim()
    if (!projectId || !userId || !canManageMembers || memberPending) return
    setMemberPending(true)
    setMemberError('')
    try {
      const member = await addProjectMember(projectId, userId, newMemberRole)
      setMembers((items) => [...items, member])
      setNewMemberUserId('')
      setMessage(`已添加项目成员：${member.user_id}`)
    } catch (caught) {
      setMemberError(caught instanceof Error ? caught.message : '添加项目成员失败')
    } finally {
      setMemberPending(false)
    }
  }

  const handleExternalModelToggle = async () => {
    if (!projectId || !currentProject || !canManageMembers || policyPending) return
    const nextEnabled = !currentProject.external_model_enabled
    if (
      nextEnabled
      && !window.confirm('启用后，脱敏后的项目流程和指令可能发送给外部模型供应商。确定允许调用吗？')
    ) {
      return
    }
    setPolicyPending(true)
    setMemberError('')
    try {
      const updated = await updateProjectSettings(projectId, nextEnabled)
      setProjects((items) => items.map((item) => (item.id === updated.id ? updated : item)))
      setMessage(updated.external_model_enabled ? '项目已允许调用外部模型' : '项目已切换为仅本地模式')
    } catch (caught) {
      setMemberError(caught instanceof Error ? caught.message : '更新外部模型策略失败')
    } finally {
      setPolicyPending(false)
    }
  }

  const handleMemberRoleChange = async (member: ProjectMember, role: ProjectRole) => {
    if (!projectId || !canManageMembers || role === member.role || memberPending) return
    setMemberPending(true)
    setMemberError('')
    try {
      const updated = await updateProjectMember(projectId, member.user_id, role)
      setMembers((items) => items.map((item) => (item.user_id === updated.user_id ? updated : item)))
      setMessage(`已更新 ${updated.user_id} 的项目角色`)
    } catch (caught) {
      setMemberError(caught instanceof Error ? caught.message : '更新项目角色失败')
    } finally {
      setMemberPending(false)
    }
  }

  const handleRemoveMember = async (member: ProjectMember) => {
    if (!projectId || !canManageMembers || memberPending) return
    if (member.role === 'project_admin' && members.filter((item) => item.role === 'project_admin').length <= 1) {
      setMemberError('项目必须保留至少一名项目管理员。')
      return
    }
    if (!window.confirm(`确定移除项目成员 ${member.user_id} 吗？`)) return
    setMemberPending(true)
    setMemberError('')
    try {
      await removeProjectMember(projectId, member.user_id)
      setMembers((items) => items.filter((item) => item.user_id !== member.user_id))
      setMessage(`已移除项目成员：${member.user_id}`)
    } catch (caught) {
      setMemberError(caught instanceof Error ? caught.message : '移除项目成员失败')
    } finally {
      setMemberPending(false)
    }
  }

  const handleCreateProcess = async () => {
    if (!projectId) {
      setError('请先选择项目。')
      return
    }
    const name = window.prompt('流程名称')?.trim()
    if (!name) return
    setProjectPending(true)
    try {
      const detail = await createProcess(projectId, name)
      const items = await listProcesses(projectId)
      setProcesses(items)
      await loadProcess(detail.id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建流程失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleRelease = async () => {
    if (!processId || baseRevision === null || releaseNo !== null || !canApproveProject) return
    if (graph.version !== baseRevision) {
      setError('当前画布有未保存修改，请先通过项目模式保存。')
      return
    }
    if (!window.confirm('发布当前修订后将不可直接修改，是否继续？')) return
    setProjectPending(true)
    try {
      const result = await releaseProcess(processId, baseRevision)
      setReleaseNo(result.release_no)
      setRevisions((items) =>
        items.map((item) =>
          item.revision_no === result.revision_no
            ? { ...item, release_no: result.release_no, lifecycle_state: result.lifecycle_state }
            : item,
        ),
      )
      setMessage(`已发布版本 ${result.release_no}`)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '发布失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleRevisionChange = async (value: string) => {
    setSelectedRevision(value)
    if (!processId || !value) return
    const revisionNo = Number(value)
    setProjectPending(true)
    try {
      const revision = await getRevision(processId, revisionNo)
      reset(layoutGraph(normalizeGraph(revision.graph)))
      setReleaseNo(revision.release_no)
      setReadOnlyRevision(revisionNo === baseRevision ? null : revisionNo)
      setMessage(
        revision.release_no
          ? `已查看发布版本 ${revision.release_no} · 修订 ${revision.revision_no}`
          : `已查看修订 ${revision.revision_no}（只读回看）`,
      )
      setError('')
      fitCanvas()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '读取修订失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleCreateDraft = async () => {
    if (!processId || baseRevision === null || releaseNo === null || !canEditProject) return
    setProjectPending(true)
    try {
      const revision = await createDraftFromRelease(processId, baseRevision)
      reset(layoutGraph(normalizeGraph(revision.graph)))
      setBaseRevision(revision.revision_no)
      setSelectedRevision(String(revision.revision_no))
      setReleaseNo(null)
      setReadOnlyRevision(null)
      setRevisions((items) => [revision, ...items])
      setProcesses((items) =>
        items.map((process) =>
          process.id === processId
            ? { ...process, current_revision: revision.revision_no, status: 'DRAFT' }
            : process,
        ),
      )
      setMessage(`已创建草稿修订 ${revision.revision_no}`)
      setError('')
      fitCanvas()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '创建草稿失败')
    } finally {
      setProjectPending(false)
    }
  }

  const handleSave = async () => {
    if (!processId || baseRevision === null || isReadOnly || projectPending || pending) return
    setProjectPending(true)
    try {
      const result = await savePersistedFlow(processId, baseRevision, graph)
      commitGraph(result.graph)
      setBaseRevision(result.result_revision)
      setSelectedRevision(String(result.result_revision))
      setReleaseNo(null)
      setProcesses((items) =>
        items.map((process) =>
          process.id === processId
            ? { ...process, current_revision: result.result_revision, status: 'DRAFT' }
            : process,
        ),
      )
      setRevisions((items) => [
        {
          revision_no: result.result_revision,
          release_no: null,
          lifecycle_state: 'DRAFT',
          schema_version: result.graph.schema_version,
          created_by: 'local-user',
          created_at: new Date().toISOString(),
        },
        ...items.filter((item) => item.revision_no !== result.result_revision),
      ])
      setMessage(`已保存修订 ${result.result_revision}`)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '保存失败')
    } finally {
      setProjectPending(false)
    }
  }

  const visualNodes = useMemo<VisualNode[]>(
    () => {
      const laneNodes: LaneNodeModel[] = laneFrames(graph).map((frame) => {
        const lane = graph.lanes.find((item) => item.id === frame.id)!
        return {
          id: `lane-visual-${lane.id}`,
          type: 'lane',
          position: { x: frame.x, y: frame.y },
          style: { width: frame.width, height: frame.height, zIndex: -2 },
          data: {
            label: lane.label,
            color: lane.color,
            direction: graph.direction,
            nodeCount: graph.nodes.filter((node) => node.lane_id === lane.id).length,
          } satisfies LaneNodeData,
          draggable: false,
          selectable: false,
          deletable: false,
          connectable: false,
          focusable: false,
          zIndex: -2,
        }
      })
      const businessNodes: BusinessNodeModel[] = graph.nodes.map((node) => ({
        id: node.id,
        type: 'business',
        position: { ...(graph.layout[node.id] ?? { x: 0, y: 0 }) },
        style: nodeDimensions(node.type),
        data: {
          label: node.label,
          description: node.description,
          nodeType: node.type,
          direction: graph.direction,
          icon: node.icon,
          tcode: node.sap.tcodes[0]?.code ?? null,
          tcodeStatus: node.sap.tcodes[0]?.status ?? null,
          gapStatus: node.sap.gap.status,
        } satisfies BusinessNodeData,
        selected: node.id === selectedNodeId,
        zIndex: 2,
      }))
      return [...laneNodes, ...businessNodes]
    },
    [graph, selectedNodeId],
  )
  const [nodes, setNodes, onNodesChange] = useNodesState<VisualNode>(visualNodes)

  useEffect(() => setNodes(visualNodes), [setNodes, visualNodes])

  const visualEdges = useMemo<Edge[]>(
    () =>
      graph.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label ?? undefined,
        selected: edge.id === selectedEdgeId,
        deletable: !isReadOnly,
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
        style: { stroke: '#68736d', strokeWidth: 1.7 },
        labelStyle: { fill: '#3f4944', fontSize: 12, fontWeight: 600 },
        labelBgStyle: { fill: '#f7f7f4', fillOpacity: 0.94 },
      })),
    [graph.edges, isReadOnly, selectedEdgeId],
  )

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const command = instruction.trim()
    if (!command || pending) return
    if (isReadOnly) {
      setError('当前流程为只读状态，请切换到可编辑草稿或联系项目管理员。')
      return
    }
    setPending(true)
    setError('')
    setMessage('正在分析流程变更')
    const controller = new AbortController()
    abortRef.current = controller
    const baseVersion = processId ? baseRevision ?? graph.version : graph.version
    if (processId && graph.version !== baseVersion) {
      setError('当前画布有未保存修改，请先保存后再执行自然语言修改。')
      setMessage('当前画布未变更')
      setPending(false)
      abortRef.current = null
      return
    }
    try {
      const response = processId
        ? await modifyPersistedFlow(processId, baseVersion, command, controller.signal)
        : await modifyFlowchart(graph, command, controller.signal)
      if (useFlowStore.getState().graph.version !== baseVersion) {
        throw new ApiError('画布已发生变化，本次响应未应用。', 'STALE_RESPONSE')
      }
      commitGraph(layoutGraph(normalizeGraph(response.graph)))
      if (processId && 'result_revision' in response) {
        setBaseRevision(response.result_revision)
        setSelectedRevision(String(response.result_revision))
        setProcesses((items) =>
          items.map((process) =>
            process.id === processId
              ? { ...process, current_revision: response.result_revision, status: 'DRAFT' }
              : process,
          ),
        )
        setRevisions((items) => [
          {
            revision_no: response.result_revision,
            release_no: null,
            lifecycle_state: 'DRAFT',
            schema_version: response.graph.schema_version,
            created_by: 'local-user',
            created_at: new Date().toISOString(),
          },
          ...items.filter((item) => item.revision_no !== response.result_revision),
        ])
        setReleaseNo(null)
      }
      fitCanvas()
      setInstruction('')
      const evidenceLabel = 'evidence' in response && response.evidence.length
        ? ` · ${response.evidence.length} 条证据`
        : ''
      setMessage(
        `${response.applied_patch.change_summary}${evidenceLabel} · ${response.metrics.latency_ms} ms · ${response.metrics.provider}`,
      )
      if (response.warnings.length) setError(response.warnings.join(' '))
    } catch (caught) {
      if ((caught as Error).name === 'AbortError') {
        setMessage('已取消本次修改')
      } else if (caught instanceof ApiError && caught.code === 'REQUEST_TIMEOUT') {
        setError(`${caught.message} 原指令已保留，可直接重试。`)
        setMessage('当前画布未变更')
      } else if (caught instanceof ApiError && caught.code === 'REVISION_CONFLICT') {
        setError(`${caught.message} 可先导出当前 JSON 备份，再重新打开流程。`)
        setMessage('当前画布未变更')
      } else {
        setError(caught instanceof Error ? caught.message : '流程修改失败')
        setMessage('当前画布未变更')
      }
    } finally {
      setPending(false)
      abortRef.current = null
    }
  }

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (isReadOnly) return
      if (!connection.source || !connection.target || connection.source === connection.target) return
      const edgeId = createId('edge')
      commitGraph({
        ...graph,
        version: graph.version + 1,
        edges: [
          ...graph.edges,
          {
            id: edgeId,
            source: connection.source,
            target: connection.target,
            label: null,
          },
        ],
      })
      setSelectedNodeId(null)
      setSelectedEdgeId(edgeId)
    },
    [commitGraph, graph, isReadOnly],
  )

  const handleImport = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    try {
      const parsed = JSON.parse(await file.text()) as unknown
      if (
        !parsed ||
        typeof parsed !== 'object' ||
        !Array.isArray((parsed as { nodes?: unknown }).nodes) ||
        !Array.isArray((parsed as { edges?: unknown }).edges)
      ) {
        throw new Error('文件不是有效的 SAP AI Flow JSON。')
      }
      const normalized = normalizeGraph(parsed)
      commitGraph(Object.keys(normalized.layout ?? {}).length ? normalized : layoutGraph(normalized))
      setSelectedNodeId(null)
      setSelectedEdgeId(null)
      fitCanvas()
      setMessage(`已导入 ${file.name}`)
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '导入失败')
    }
  }

  const exportJson = () => {
    downloadBlob(
      new Blob([JSON.stringify(graph, null, 2)], { type: 'application/json;charset=utf-8' }),
      buildExportFilename(graph.title, 'json'),
    )
    setMessage('JSON 已导出')
  }

  const exportBlueprintFile = async (format: 'markdown' | 'docx') => {
    if (!processId || (!selectedRevision && baseRevision === null)) {
      setError('请先打开项目流程。')
      return
    }
    setProjectPending(true)
    try {
      const revisionNo = Number(selectedRevision || baseRevision)
      const result = await exportBlueprint(processId, revisionNo, format)
      downloadBlob(result.blob, result.filename)
      setMessage(format === 'docx' ? 'Word 蓝图已导出' : 'Markdown 蓝图已导出')
      setError('')
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '蓝图导出失败')
    } finally {
      setProjectPending(false)
    }
  }

  const exportSvg = async () => {
    const viewport = document.querySelector('.react-flow__viewport') as HTMLElement | null
    if (!viewport || getNodes().length === 0) return
    setMessage('正在生成 SVG')
    setError('')
    try {
      const { width, height, style } = getExportViewport(getNodesBounds(getNodes()))
      const dataUrl = await toSvg(viewport, {
        backgroundColor: '#f7f7f4',
        width,
        height,
        style,
      })
      downloadUrl(dataUrl, buildExportFilename(graph.title, 'svg'))
      setMessage('SVG 已导出')
    } catch {
      setError('SVG 导出失败，请重试。')
    }
  }

  const exportPng = async () => {
    const viewport = document.querySelector('.react-flow__viewport') as HTMLElement | null
    if (!viewport || getNodes().length === 0) return
    setMessage('正在生成 PNG')
    setError('')
    try {
      const { width, height, style } = getExportViewport(getNodesBounds(getNodes()))
      const dataUrl = await toPng(viewport, {
        backgroundColor: '#f7f7f4',
        width,
        height,
        style,
        pixelRatio: 2,
      })
      downloadUrl(dataUrl, buildExportFilename(graph.title, 'png'))
      setMessage('PNG 已导出')
    } catch {
      setError('PNG 导出失败，请重试。')
    }
  }

  const toggleDirection = () => {
    if (isReadOnly) return
    const direction = graph.direction === 'TB' ? 'LR' : 'TB'
    commitGraph(layoutGraph({ ...graph, version: graph.version + 1, direction }))
    fitCanvas()
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-mark" aria-hidden="true">
          <Bot size={20} />
        </div>
        <div className="brand-copy">
          <strong>SAP AI Flow</strong>
          <span>{graph.title}</span>
        </div>
        <div className="header-status">
          <span className={pending || authActionPending ? 'status-dot is-pending' : 'status-dot'} />
          {requiresSignIn
            ? '未登录'
            : isReadOnly
            ? readOnlyRevision !== null
              ? `只读 · v${readOnlyRevision}`
              : currentProjectRole === 'viewer'
                ? '只读 · 查看者'
                : '只读 · 已发布'
            : pending
              ? '处理中'
              : '已就绪'}
        </div>
        <div className="project-context" aria-label="项目与流程">
          <select
            aria-label="项目"
            value={projectId}
            disabled={projectPending || requiresSignIn}
            onChange={(event) => void handleProjectChange(event.target.value)}
          >
            <option value="">本地演示</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <select
            aria-label="流程"
            value={processId}
            disabled={!projectId || projectPending}
            onChange={(event) => void loadProcess(event.target.value)}
          >
            <option value="">选择流程</option>
            {processes.map((process) => (
              <option key={process.id} value={process.id}>
                {process.name} · v{process.current_revision}
              </option>
            ))}
          </select>
          {processId && (
            <select
              aria-label="修订"
              value={selectedRevision}
              disabled={projectPending}
              onChange={(event) => void handleRevisionChange(event.target.value)}
            >
              {revisions.map((revision) => (
                <option key={revision.revision_no} value={revision.revision_no}>
                  {revision.release_no ? `发布 ${revision.release_no}` : '草稿'} · v{revision.revision_no}
                </option>
              ))}
            </select>
          )}
          <button
            className="icon-button"
            title="新建项目"
            aria-label="新建项目"
            disabled={projectPending || requiresSignIn}
            onClick={() => void handleCreateProject()}
          >
            <FolderPlus size={17} />
          </button>
          {canManageMembers && (
            <button
              className="icon-button member-button"
              title="项目成员"
              aria-label="项目成员"
              disabled={projectPending}
              onClick={() => void handleOpenMemberDialog()}
            >
              <Users size={17} />
            </button>
          )}
          <button
            className="icon-button"
            title="新建流程"
            aria-label="新建流程"
            disabled={!projectId || projectPending || !canEditProject}
            onClick={() => void handleCreateProcess()}
          >
            <GitBranchPlus size={17} />
          </button>
          {processId && (
            <>
              {releaseNo !== null && readOnlyRevision === null && (
                <button
                  className="icon-button"
                  title="从发布版本创建新草稿"
                  aria-label="从发布版本创建新草稿"
                  disabled={projectPending || !canEditProject}
                  onClick={() => void handleCreateDraft()}
                >
                  <CopyPlus size={17} />
                </button>
              )}
              <button
                className="icon-button"
                title="保存画布修订"
                aria-label="保存画布修订"
                disabled={projectPending || pending || isReadOnly || graph.version === baseRevision}
                onClick={() => void handleSave()}
              >
                <Save size={17} />
              </button>
              <button
                className="icon-button"
                title="发布当前修订"
                aria-label="发布当前修订"
                disabled={
                  projectPending ||
                  readOnlyRevision !== null ||
                  releaseNo !== null ||
                  graph.version !== baseRevision ||
                  !canApproveProject
                }
                onClick={() => void handleRelease()}
              >
                <SendToBack size={17} />
              </button>
            </>
          )}
        </div>
        {authSession.configured && (
          <div className="auth-control">
            {authSession.authenticated && (
              <span className="auth-control__identity" title={authSession.userId ?? undefined}>
                {authSession.displayName}
              </span>
            )}
            <button
              type="button"
              className="icon-button auth-button"
              title={
                authError ||
                (authSession.authenticated
                  ? `退出登录${authSession.displayName ? ` · ${authSession.displayName}` : ''}`
                  : '登录')
              }
              aria-label={authSession.authenticated ? '退出登录' : '登录'}
              disabled={authActionPending}
              onClick={() => void (authSession.authenticated ? onSignOut() : onSignIn())}
            >
              {authActionPending ? (
                <LoaderCircle size={17} className="spin" />
              ) : authSession.authenticated ? (
                <LogOut size={17} />
              ) : (
                <LogIn size={17} />
              )}
            </button>
          </div>
        )}
      </header>

      <nav className="toolbar" aria-label="流程工具栏">
        <div className="toolbar__group">
          <button
            className="icon-button"
            title="新建流程"
            aria-label="新建流程"
            disabled={isReadOnly}
            onClick={() => {
              if (isReadOnly) return
              if (graph.nodes.length > 0 && !window.confirm('新建流程将清空当前画布，是否继续？')) return
              reset(createEmptyGraph())
              setSelectedNodeId(null)
              setSelectedEdgeId(null)
              setMessage('已新建空白流程')
              fitCanvas()
            }}
          >
            <FilePlus2 size={18} />
          </button>
          <button
            className="icon-button"
            title="导入 JSON"
            aria-label="导入 JSON"
            disabled={isReadOnly}
            onClick={() => importRef.current?.click()}
          >
            <Upload size={18} />
          </button>
          <input ref={importRef} type="file" accept="application/json,.json" hidden onChange={handleImport} />
          <button className="icon-button" title="导出 JSON" aria-label="导出 JSON" onClick={exportJson}>
            <FileJson size={18} />
          </button>
          <button className="icon-button" title="导出 SVG" aria-label="导出 SVG" onClick={exportSvg}>
            <FileCode2 size={18} />
          </button>
          <button className="icon-button" title="导出 PNG" aria-label="导出 PNG" onClick={exportPng}>
            <ImageDown size={18} />
          </button>
          <button
            className="icon-button"
            title="导出 Markdown 蓝图"
            aria-label="导出 Markdown 蓝图"
            disabled={!processId || projectPending}
            onClick={() => void exportBlueprintFile('markdown')}
          >
            <FileText size={18} />
          </button>
          <button
            className="icon-button"
            title="导出 Word 蓝图"
            aria-label="导出 Word 蓝图"
            disabled={!processId || projectPending}
            onClick={() => void exportBlueprintFile('docx')}
          >
            <FileDown size={18} />
          </button>
        </div>
        <span className="toolbar__separator" />
        <div className="toolbar__group">
          <button
            className="icon-button"
            title="撤销"
            aria-label="撤销"
            disabled={!past.length || isReadOnly}
            onClick={undo}
          >
            <Undo2 size={18} />
          </button>
          <button
            className="icon-button"
            title="重做"
            aria-label="重做"
            disabled={!future.length || isReadOnly}
            onClick={redo}
          >
            <Redo2 size={18} />
          </button>
          <button
            className="icon-button"
            title="自动布局"
            aria-label="自动布局"
            disabled={isReadOnly}
            onClick={() => {
              if (isReadOnly) return
              commitGraph(layoutGraph({ ...graph, version: graph.version + 1 }))
              fitCanvas()
            }}
          >
            <LayoutDashboard size={18} />
          </button>
        </div>
        <span className="toolbar__separator" />
        <div className="segmented" aria-label="布局方向">
          <button
            className={graph.direction === 'TB' ? 'is-active' : ''}
            disabled={isReadOnly}
            onClick={toggleDirection}
          >
            纵向
          </button>
          <button
            className={graph.direction === 'LR' ? 'is-active' : ''}
            disabled={isReadOnly}
            onClick={toggleDirection}
          >
            横向
          </button>
        </div>
        <button
          className="icon-button toolbar__inspector-toggle"
          title="属性面板"
          aria-label="属性面板"
          onClick={() => setInspectorOpen((value) => !value)}
        >
          <PanelRight size={18} />
        </button>
      </nav>

      <main className={`workspace${inspectorOpen ? '' : ' inspector-closed'}`}>
        <section className="canvas-region" aria-label="流程图画布">
          <ReactFlow<VisualNode>
            nodes={nodes}
            edges={visualEdges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onConnect={handleConnect}
            nodesDraggable={!isReadOnly}
            nodesConnectable={!isReadOnly}
            onNodeClick={(_, node) => {
              setSelectedEdgeId(null)
              setSelectedNodeId(node.type === 'business' ? node.id : null)
            }}
            onEdgeClick={(_, edge) => {
              setSelectedNodeId(null)
              setSelectedEdgeId(edge.id)
            }}
            onPaneClick={() => {
              setSelectedNodeId(null)
              setSelectedEdgeId(null)
            }}
            onNodeDragStop={(_, node) => {
              if (isReadOnly) return
              if (node.type !== 'business') return
              const laneId = laneIdAtPosition(graph, node.position, nodeDimensions(node.data.nodeType))
              commitGraph({
                ...graph,
                version: graph.version + 1,
                nodes: graph.nodes.map((item) =>
                  item.id === node.id ? { ...item, lane_id: laneId } : item,
                ),
                layout: { ...graph.layout, [node.id]: node.position },
              })
            }}
            onNodesDelete={(deleted: Node[]) => {
              if (isReadOnly) return
              const ids = new Set(
                deleted.filter((node) => node.type === 'business').map((node) => node.id),
              )
              if (ids.size === 0) return
              commitGraph({
                ...graph,
                version: graph.version + 1,
                nodes: graph.nodes.filter((node) => !ids.has(node.id)),
                edges: graph.edges.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)),
                layout: Object.fromEntries(Object.entries(graph.layout).filter(([id]) => !ids.has(id))),
              })
              setSelectedNodeId(null)
              setSelectedEdgeId(null)
            }}
            onEdgesDelete={(deleted: Edge[]) => {
              if (isReadOnly) return
              const ids = new Set(deleted.map((edge) => edge.id))
              commitGraph({
                ...graph,
                version: graph.version + 1,
                edges: graph.edges.filter((edge) => !ids.has(edge.id)),
              })
              setSelectedEdgeId(null)
            }}
            fitView
            fitViewOptions={{
              padding: 0.18,
              minZoom: window.innerWidth <= 720 ? 0.55 : 0.25,
              maxZoom: 1.15,
            }}
            minZoom={0.25}
            maxZoom={1.8}
            deleteKeyCode={['Backspace', 'Delete']}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#cbd0cb" />
            <Controls position="bottom-left" showInteractive={false} />
            <MiniMap
              position="bottom-right"
              pannable
              zoomable
              nodeColor={(node) =>
                node.type === 'lane'
                  ? (node.data as LaneNodeData).color
                  : nodeColor((node.data as BusinessNodeData).nodeType)
              }
              maskColor="rgba(247, 247, 244, 0.78)"
            />
            {graph.nodes.length === 0 && (
              <div className="empty-canvas">
                <Bot size={28} />
                <strong>空白流程</strong>
              </div>
            )}
          </ReactFlow>
        </section>
        {inspectorOpen && (
          <Inspector
            selectedNodeId={selectedNodeId}
            selectedEdgeId={selectedEdgeId}
            onClearSelection={() => {
              setSelectedNodeId(null)
              setSelectedEdgeId(null)
            }}
            projectId={projectId}
            processId={processId}
            baseRevision={baseRevision}
            readOnly={isReadOnly}
            canApprove={canApproveProject}
            onPersistedGraph={(nextGraph, revision) => {
              commitGraph(layoutGraph(normalizeGraph(nextGraph)))
              setBaseRevision(revision)
              setSelectedRevision(String(revision))
              setReleaseNo(null)
              setReadOnlyRevision(null)
              setProcesses((items) =>
                items.map((process) =>
                  process.id === processId
                    ? { ...process, current_revision: revision, status: 'DRAFT' }
                    : process,
                ),
              )
            }}
          />
        )}
      </main>

      {memberDialogOpen && canManageMembers && (
        <div
          className="member-dialog__backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setMemberDialogOpen(false)
          }}
        >
          <section className="member-dialog" role="dialog" aria-modal="true" aria-labelledby="member-dialog-title">
            <div className="member-dialog__header">
              <div>
                <span className="member-dialog__eyebrow">项目访问</span>
                <h2 id="member-dialog-title">项目成员</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                title="关闭"
                aria-label="关闭项目成员"
                onClick={() => setMemberDialogOpen(false)}
              >
                <X size={18} />
              </button>
            </div>
            <p className="member-dialog__project">
              {currentProject?.name ?? '当前项目'}
            </p>
            <div className="member-dialog__policy">
              <div className="member-dialog__policy-copy">
                <strong>外部模型</strong>
                <span>{currentProject?.external_model_enabled ? '允许调用' : '仅本地'}</span>
              </div>
              <button
                type="button"
                className="policy-switch"
                role="switch"
                aria-checked={currentProject?.external_model_enabled ?? false}
                aria-label="允许调用外部模型"
                title={currentProject?.external_model_enabled ? '切换为仅本地' : '允许调用外部模型'}
                disabled={policyPending}
                onClick={() => void handleExternalModelToggle()}
              >
                <span aria-hidden="true" />
              </button>
            </div>
            <form className="member-dialog__add" onSubmit={(event) => void handleAddMember(event)}>
              <label>
                用户 ID
                <input
                  value={newMemberUserId}
                  onChange={(event) => setNewMemberUserId(event.target.value)}
                  placeholder="输入用户 ID"
                  maxLength={80}
                  autoComplete="off"
                />
              </label>
              <label>
                项目角色
                <select
                  value={newMemberRole}
                  onChange={(event) => setNewMemberRole(event.target.value as ProjectRole)}
                >
                  {Object.entries(projectRoleLabels).map(([role, label]) => (
                    <option key={role} value={role}>{label}</option>
                  ))}
                </select>
              </label>
              <button type="submit" className="secondary-button" disabled={!newMemberUserId.trim() || memberPending}>
                <UserPlus size={16} />
                添加成员
              </button>
            </form>
            {memberError && <p className="member-dialog__error" role="alert">{memberError}</p>}
            <div className="member-dialog__list" aria-live="polite">
              {memberPending && members.length === 0 ? (
                <p className="member-dialog__empty">正在读取成员…</p>
              ) : members.length === 0 ? (
                <p className="member-dialog__empty">暂无项目成员</p>
              ) : (
                members.map((member) => (
                  <div className="member-row" key={member.user_id}>
                    <div className="member-row__identity">
                      <strong>{member.user_id}</strong>
                      <small>由 {member.updated_by} 更新</small>
                    </div>
                    <select
                      aria-label={`${member.user_id} 的角色`}
                      value={member.role}
                      title={
                        member.role === 'project_admin' && projectAdminCount <= 1
                          ? '项目必须保留至少一名项目管理员'
                          : `修改 ${member.user_id} 的角色`
                      }
                      disabled={
                        memberPending || (member.role === 'project_admin' && projectAdminCount <= 1)
                      }
                      onChange={(event) => void handleMemberRoleChange(member, event.target.value as ProjectRole)}
                    >
                      {Object.entries(projectRoleLabels).map(([role, label]) => (
                        <option key={role} value={role}>{label}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="icon-button danger"
                      title={
                        member.role === 'project_admin' && projectAdminCount <= 1
                          ? '项目必须保留至少一名项目管理员'
                          : `移除 ${member.user_id}`
                      }
                      aria-label={`移除 ${member.user_id}`}
                      disabled={
                        memberPending || (member.role === 'project_admin' && projectAdminCount <= 1)
                      }
                      onClick={() => void handleRemoveMember(member)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}

      <footer className="command-dock">
        <div className="command-dock__status" role="status">
          <span>{message}</span>
          {(error || authError) && (
            <span className="command-dock__error">{error || authError}</span>
          )}
        </div>
        <form onSubmit={handleSubmit}>
          <Bot size={20} aria-hidden="true" />
          <textarea
            value={instruction}
            disabled={isReadOnly}
            onChange={(event) => setInstruction(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
            rows={1}
            maxLength={4000}
            placeholder="输入流程修改指令"
            aria-label="流程修改指令"
          />
          {pending ? (
            <button
              type="button"
              className="command-button cancel"
              onClick={() => abortRef.current?.abort()}
            >
              <LoaderCircle size={18} className="spin" />
              <span>取消</span>
            </button>
          ) : (
            <button
              type="submit"
              className="command-button"
              disabled={!instruction.trim() || isReadOnly}
            >
              <Send size={18} />
              <span>执行</span>
            </button>
          )}
        </form>
      </footer>
    </div>
  )
}

export default function App() {
  const [authSession, setAuthSession] = useState<AuthSession | null>(null)
  const [authError, setAuthError] = useState('')
  const [authActionPending, setAuthActionPending] = useState(false)

  const loadAuthSession = useCallback(async () => {
    setAuthError('')
    try {
      setAuthSession(await initializeOidcAuth())
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : '登录回调处理失败。')
    }
  }, [])

  useEffect(() => {
    void loadAuthSession()
  }, [loadAuthSession])

  const handleSignIn = async () => {
    setAuthActionPending(true)
    setAuthError('')
    try {
      await startOidcSignIn()
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : '无法跳转到登录页面。')
      setAuthActionPending(false)
    }
  }

  const handleSignOut = async () => {
    setAuthActionPending(true)
    setAuthError('')
    try {
      await startOidcSignOut()
    } catch (caught) {
      setAuthError(caught instanceof Error ? caught.message : '退出登录失败。')
      setAuthActionPending(false)
    }
  }

  if (!authSession) {
    return (
      <main className="auth-bootstrap" aria-live="polite">
        <div className="brand-mark" aria-hidden="true">
          <Bot size={20} />
        </div>
        {authError ? (
          <>
            <strong>认证初始化失败</strong>
            <p>{authError}</p>
            <button type="button" className="secondary-button" onClick={() => void loadAuthSession()}>
              重试
            </button>
          </>
        ) : (
          <>
            <LoaderCircle size={20} className="spin" />
            <span>正在检查登录状态</span>
          </>
        )}
      </main>
    )
  }

  return (
    <ReactFlowProvider>
      <FlowWorkspace
        authSession={authSession}
        authActionPending={authActionPending}
        authError={authError}
        onSignIn={handleSignIn}
        onSignOut={handleSignOut}
      />
    </ReactFlowProvider>
  )
}

function getExportViewport(bounds: { x: number; y: number; width: number; height: number }) {
  const width = Math.max(1200, Math.ceil(bounds.width + 160))
  const height = Math.max(760, Math.ceil(bounds.height + 160))
  const transform = getViewportForBounds(bounds, width, height, 0.5, 2, 0.12)

  return {
    width,
    height,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.zoom})`,
    },
  }
}

function nodeColor(type: string): string {
  const colors: Record<string, string> = {
    start: '#2d7a5e',
    end: '#ad4c4c',
    task: '#3e6f98',
    decision: '#c58b2c',
    subprocess: '#745d91',
  }
  return colors[type] ?? '#68736d'
}
