import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { createSampleGraph } from '../data'
import { drawioXmlToGraph, graphToDrawioXml } from './adapter'

describe('Draw.io adapter', () => {
  it('round-trips GraphDocument IDs, lanes, topology and SAP metadata', () => {
    const source = createSampleGraph()
    source.version = 7
    source.layout = Object.fromEntries(source.nodes.map((node, index) => [
      node.id,
      { x: 100 + index * 230, y: 120 + index * 40 },
    ]))

    const xml = graphToDrawioXml(source)
    const result = drawioXmlToGraph(xml)

    expect(result.graph_id).toBe(source.graph_id)
    expect(result.version).toBe(7)
    expect(result.nodes.map((node) => node.id)).toEqual(source.nodes.map((node) => node.id))
    expect(result.edges).toEqual(source.edges)
    expect(result.lanes).toEqual(source.lanes)
    expect(result.nodes.find((node) => node.id === 'pr')?.sap.tcodes[0]).toEqual(
      source.nodes.find((node) => node.id === 'pr')?.sap.tcodes[0],
    )
    expect(result.layout.pr).toEqual(source.layout.pr)
  })

  it('infers business nodes, node types and lanes from a regular Draw.io file', () => {
    const xml = `
      <mxfile host="drawio">
        <diagram id="diagram-1" name="采购审批">
          <mxGraphModel><root>
            <mxCell id="0"/><mxCell id="1" parent="0"/>
            <mxCell id="lane-a" parent="1" vertex="1" value="采购部" style="swimlane;fillColor=#dae8fc;">
              <mxGeometry x="20" y="40" width="500" height="300" as="geometry"/>
            </mxCell>
            <mxCell id="start" parent="lane-a" vertex="1" value="开始" style="ellipse;fillColor=#d5e8d4;">
              <mxGeometry x="30" y="40" width="100" height="50" as="geometry"/>
            </mxCell>
            <mxCell id="decision" parent="lane-a" vertex="1" value="审批通过？" style="rhombus;fillColor=#fff2cc;">
              <mxGeometry x="200" y="120" width="120" height="80" as="geometry"/>
            </mxCell>
            <mxCell id="tag" parent="lane-a" vertex="1" value="SAP" style="rounded=1;fontSize=9;"/>
            <mxCell id="edge-a" parent="1" edge="1" source="start" target="decision" value="提交">
              <mxGeometry relative="1" as="geometry"/>
            </mxCell>
          </root></mxGraphModel>
        </diagram>
      </mxfile>`

    const result = drawioXmlToGraph(xml)

    expect(result.title).toBe('采购审批')
    expect(result.lanes).toEqual([{ id: 'lane-a', label: '采购部', color: '#dae8fc' }])
    expect(result.nodes.map(({ id, type, lane_id }) => ({ id, type, lane_id }))).toEqual([
      { id: 'start', type: 'task', lane_id: 'lane-a' },
      { id: 'decision', type: 'decision', lane_id: 'lane-a' },
    ])
    expect(result.edges).toEqual([{ id: 'edge-a', source: 'start', target: 'decision', label: '提交' }])
    expect(result.layout.start).toEqual({ x: 50, y: 80 })
  })

  it('rejects malformed XML and non-Diagram XML', () => {
    expect(() => drawioXmlToGraph('<mxfile>')).toThrow('Draw.io XML 无法解析')
    expect(() => drawioXmlToGraph('<root/>')).toThrow('缺少 mxGraphModel')
  })

  it('imports the current equipment-rental Draw.io source without decorative cells', () => {
    const sourcePath = path.resolve(process.cwd(), '../../设备租赁采购流程方案/设备租赁采购流程.drawio')
    const graph = drawioXmlToGraph(fs.readFileSync(sourcePath, 'utf8'))

    expect(graph.title).toBe('MM.100.70 设备租赁采购流程')
    expect(graph.lanes.map((lane) => lane.id)).toEqual(['up', 'mkt', 'fin', 'wh', 'down'])
    expect(graph.nodes.map((node) => node.id)).toEqual([
      'us', 's', 'n10', 'n20', 'n30', 'n40', 'n60', 'n120', 'e', 'n50',
      'n70', 'd1', 'n80', 'n90', 'n100', 'n110', 'bad', 'sub1', 'sub2', 'sub3',
    ])
    expect(graph.edges).toHaveLength(19)
    expect(graph.nodes.find((node) => node.id === 'd1')).toMatchObject({
      type: 'decision',
      lane_id: 'wh',
      label: '数量/实物\n一致？',
    })
    expect(graph.nodes.some((node) => node.label === 'SAP')).toBe(false)
    expect(graph.layout.n70).toEqual({ x: 1225, y: 230 })
  })
})
