import { nodeIconKeys } from './types'
import type { GraphDocument, NodeIcon, Swimlane } from './types'

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
    lanes: [],
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
      { id: 'start', type: 'start', label: '开始', description: null, icon: null, lane_id: 'lane_sales' },
      {
        id: 'submit',
        type: 'task',
        label: '提交销售订单',
        description: '录入客户、物料和数量',
        icon: 'file-text',
        lane_id: 'lane_sales',
      },
      {
        id: 'credit',
        type: 'decision',
        label: '信用检查',
        description: '检查客户信用额度',
        icon: 'shield-check',
        lane_id: 'lane_finance',
      },
      {
        id: 'ship',
        type: 'task',
        label: '仓库出库',
        description: '创建并确认出库单',
        icon: 'package',
        lane_id: 'lane_warehouse',
      },
      {
        id: 'rejected',
        type: 'end',
        label: '订单拒绝',
        description: '信用检查未通过',
        icon: null,
        lane_id: 'lane_finance',
      },
      { id: 'end', type: 'end', label: '结束', description: null, icon: null, lane_id: 'lane_warehouse' },
    ],
    edges: [
      { id: 'edge_1', source: 'start', target: 'submit', label: null },
      { id: 'edge_2', source: 'submit', target: 'credit', label: null },
      { id: 'edge_3', source: 'credit', target: 'ship', label: '通过' },
      { id: 'edge_4', source: 'credit', target: 'rejected', label: '拒绝' },
      { id: 'edge_5', source: 'ship', target: 'end', label: null },
    ],
    lanes: [
      { id: 'lane_sales', label: '销售', color: '#52796f' },
      { id: 'lane_finance', label: '财务与风控', color: '#a36f3f' },
      { id: 'lane_warehouse', label: '仓储', color: '#5b7394' },
    ],
    layout: {},
  }
}

export function normalizeGraph(graph: GraphDocument): GraphDocument {
  const source = graph as GraphDocument & { lanes?: Swimlane[] }
  const lanes = Array.isArray(source.lanes)
    ? source.lanes.slice(0, 20).map((lane) => ({
        ...lane,
        color: /^#[0-9a-fA-F]{6}$/.test(lane.color) ? lane.color : '#52796f',
      }))
    : []
  const laneIds = new Set(lanes.map((lane) => lane.id))
  const icons = new Set<string>(nodeIconKeys)

  return {
    ...graph,
    lanes,
    nodes: graph.nodes.map((node) => {
      const legacyNode = node as typeof node & { icon?: NodeIcon | null; lane_id?: string | null }
      return {
        ...node,
        icon: legacyNode.icon && icons.has(legacyNode.icon) ? legacyNode.icon : null,
        lane_id: legacyNode.lane_id && laneIds.has(legacyNode.lane_id) ? legacyNode.lane_id : null,
      }
    }),
  }
}
