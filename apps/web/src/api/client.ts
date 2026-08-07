import type { GraphDocument, ModifyResponse } from '../types'

const API_ROOT = import.meta.env.VITE_API_URL ?? ''

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
  const response = await fetch(`${API_ROOT}/api/v1/flowcharts/modify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
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
