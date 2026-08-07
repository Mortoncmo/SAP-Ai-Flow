import type { GraphDocument } from './types'

export function createId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID().replaceAll('-', '')}`
}

export function createEmptyGraph(): GraphDocument {
  return {
    schema_version: '1.0',
    graph_id: createId('graph'),
    version: 0,
    title: '未命名流程',
    direction: 'TB',
    nodes: [],
    edges: [],
    layout: {},
  }
}

export function createSampleGraph(): GraphDocument {
  return {
    schema_version: '1.0',
    graph_id: 'graph_sales_order_demo',
    version: 0,
    title: '销售订单审批流程',
    direction: 'TB',
    nodes: [
      { id: 'start', type: 'start', label: '开始', description: null },
      { id: 'submit', type: 'task', label: '提交销售订单', description: '录入客户、物料和数量' },
      { id: 'credit', type: 'decision', label: '信用检查', description: '检查客户信用额度' },
      { id: 'ship', type: 'task', label: '仓库出库', description: '创建并确认出库单' },
      { id: 'rejected', type: 'end', label: '订单拒绝', description: '信用检查未通过' },
      { id: 'end', type: 'end', label: '结束', description: null },
    ],
    edges: [
      { id: 'edge_1', source: 'start', target: 'submit', label: null },
      { id: 'edge_2', source: 'submit', target: 'credit', label: null },
      { id: 'edge_3', source: 'credit', target: 'ship', label: '通过' },
      { id: 'edge_4', source: 'credit', target: 'rejected', label: '拒绝' },
      { id: 'edge_5', source: 'ship', target: 'end', label: null },
    ],
    layout: {},
  }
}
