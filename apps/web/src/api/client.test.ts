import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../auth/oidc', () => ({
  clearOidcSession: vi.fn(),
  getAccessToken: vi.fn(),
}))

import { clearOidcSession, getAccessToken } from '../auth/oidc'

import {
  addProjectMember,
  API_REQUEST_TIMEOUT_MS,
  ApiError,
  createProject,
  exportBlueprint,
  listProjectAudits,
  listProjectMembers,
  listProjects,
  removeProjectMember,
  updateProjectMember,
  updateProjectSettings,
} from './client'

const getAccessTokenMock = vi.mocked(getAccessToken)
const clearOidcSessionMock = vi.mocked(clearOidcSession)

const abortableFetch: typeof fetch = (_input, init) =>
  new Promise((_resolve, reject) => {
    const signal = init?.signal
    const rejectAbort = () => reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
    if (signal?.aborted) {
      rejectAbort()
      return
    }
    signal?.addEventListener('abort', rejectAbort, { once: true })
  })

beforeEach(() => {
  getAccessTokenMock.mockReset()
  getAccessTokenMock.mockResolvedValue(undefined)
  clearOidcSessionMock.mockReset()
  clearOidcSessionMock.mockResolvedValue(undefined)
})

const member = {
  project_id: 'project / 1',
  user_id: 'consultant@example.com',
  role: 'viewer' as const,
  created_by: 'local-user',
  updated_by: 'local-user',
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:00Z',
}

describe('project member client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('loads members from the encoded project route', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([member]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(listProjectMembers('project / 1')).resolves.toEqual([member])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects/project%20%2F%201/members',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('X-Request-ID')).toMatch(/^web_[a-f0-9]+$/)
  })

  it('loads the project access audit trail from the encoded route', async () => {
    const audit = {
      id: 'audit-1',
      project_id: 'project / 1',
      action: 'project_member_added',
      before_value: { user_id: member.user_id, role: null },
      after_value: { user_id: member.user_id, role: 'viewer' },
      actor_user_id: 'local-user',
      created_at: '2026-08-10T00:00:00Z',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([audit]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(listProjectAudits('project / 1')).resolves.toEqual([audit])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects/project%20%2F%201/audits',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it('uses POST, PUT and DELETE for member mutations', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify(member), {
          status: 201,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ ...member, role: 'editor' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }))

    await addProjectMember('project / 1', member.user_id, 'viewer')
    await updateProjectMember('project / 1', member.user_id, 'editor')
    await removeProjectMember('project / 1', member.user_id)

    expect(fetchMock.mock.calls[0]).toEqual([
      '/api/v1/projects/project%20%2F%201/members',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ user_id: member.user_id, role: 'viewer' }),
      }),
    ])
    expect(fetchMock.mock.calls[1]).toEqual([
      '/api/v1/projects/project%20%2F%201/members/consultant%40example.com',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ user_id: member.user_id, role: 'editor' }),
      }),
    ])
    expect(fetchMock.mock.calls[2]).toEqual([
      '/api/v1/projects/project%20%2F%201/members/consultant%40example.com',
      expect.objectContaining({ method: 'DELETE', signal: expect.any(AbortSignal) }),
    ])
  })

  it('preserves structured API errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ error: { code: 'LAST_PROJECT_ADMIN', message: '项目必须保留管理员。' } }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const error = await updateProjectMember('project-1', 'local-user', 'editor').catch(
      (caught) => caught,
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      name: 'Error',
      message: '项目必须保留管理员。',
      code: 'LAST_PROJECT_ADMIN',
    })
  })
})

describe('project settings client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('updates the external model policy through the encoded project route', async () => {
    const project = {
      id: 'project / 1',
      name: '模型策略项目',
      customer_name: null,
      sap_context: {},
      external_model_enabled: true,
      current_role: 'project_admin',
      created_at: '2026-08-09T00:00:00Z',
      updated_at: '2026-08-09T00:01:00Z',
    }
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(project), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(updateProjectSettings('project / 1', true)).resolves.toEqual(project)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/projects/project%20%2F%201',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ external_model_enabled: true }),
      }),
    )
  })
})

describe('blueprint export client', () => {
  afterEach(() => vi.restoreAllMocks())

  it('rejects a failed download with the structured API error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 'EXPORT_RENDER_FAILED',
            message: '蓝图渲染失败，请稍后重试。',
          },
        }),
        { status: 503, headers: { 'Content-Type': 'application/json' } },
      ),
    )

    const error = await exportBlueprint('process / 1', 3, 'docx').catch(
      (caught) => caught,
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      message: '蓝图渲染失败，请稍后重试。',
      code: 'EXPORT_RENDER_FAILED',
    })
  })

  it('creates an export job, polls completion and downloads the artifact', async () => {
    vi.useFakeTimers()
    try {
      const job = {
        export_id: 'export / 1',
        process_id: 'process / 1',
        revision_no: 3,
        format: 'markdown',
        status: 'pending',
        filename: null,
        content_length: null,
        error_code: null,
        error_message: null,
        created_at: '2026-08-09T00:00:00Z',
        started_at: null,
        completed_at: null,
        expires_at: null,
        download_url: null,
      }
      const fetchMock = vi.spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(
          new Response(JSON.stringify(job), {
            status: 202,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
        .mockResolvedValueOnce(
          new Response(JSON.stringify({
            ...job,
            status: 'completed',
            filename: 'SAP-Blueprint-采购流程-r3.md',
            content_length: 128,
            download_url: '/api/v1/processes/process%20%2F%201/exports/jobs/export%20%2F%201/download',
          }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          }),
        )
        .mockResolvedValueOnce(
          new Response('# SAP Blueprint', {
            status: 200,
            headers: {
              'Content-Disposition': "attachment; filename*=UTF-8''SAP-Blueprint-%E9%87%87%E8%B4%AD%E6%B5%81%E7%A8%8B-r3.md",
            },
          }),
        )

      const request = exportBlueprint('process / 1', 3, 'markdown')
      await vi.advanceTimersByTimeAsync(250)
      const result = await request

      expect(result.filename).toBe('SAP-Blueprint-采购流程-r3.md')
      expect(result.blob.size).toBeGreaterThan(0)
      expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
        '/api/v1/processes/process%20%2F%201/exports/jobs',
        '/api/v1/processes/process%20%2F%201/exports/jobs/export%20%2F%201',
        '/api/v1/processes/process%20%2F%201/exports/jobs/export%20%2F%201/download',
      ])
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('authenticated API requests', () => {
  afterEach(() => vi.restoreAllMocks())

  it('adds the current OIDC access token as a Bearer authorization header', async () => {
    getAccessTokenMock.mockResolvedValue('signed-access-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    await expect(listProjects()).resolves.toEqual([])
    const init = fetchMock.mock.calls[0][1]
    expect(new Headers(init?.headers).get('X-Request-ID')).toMatch(/^web_[a-f0-9]+$/)
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer signed-access-token')
  })

  it('does not replay a rejected write request after an authentication failure', async () => {
    getAccessTokenMock.mockResolvedValue('expired-access-token')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          error: { code: 'AUTHENTICATION_REQUIRED', message: '请重新登录。' },
        }),
        {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )

    await expect(createProject('不应重放')).rejects.toMatchObject({
      code: 'AUTHENTICATION_REQUIRED',
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]?.method).toBe('POST')
    expect(clearOidcSessionMock).toHaveBeenCalledTimes(1)
  })

  it('converts the client deadline into a stable timeout error', async () => {
    vi.useFakeTimers()
    try {
      vi.spyOn(globalThis, 'fetch').mockImplementation(abortableFetch)

      const request = listProjects()
      const assertion = expect(request).rejects.toMatchObject({
        message: '请求超时，当前数据未改变，请重试。',
        code: 'REQUEST_TIMEOUT',
      })
      await vi.advanceTimersByTimeAsync(API_REQUEST_TIMEOUT_MS)

      await assertion
    } finally {
      vi.useRealTimers()
    }
  })

  it('preserves an explicit user cancellation as AbortError', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(abortableFetch)
    const controller = new AbortController()
    const request = listProjects(controller.signal)

    controller.abort()

    await expect(request).rejects.toMatchObject({ name: 'AbortError' })
  })
})
