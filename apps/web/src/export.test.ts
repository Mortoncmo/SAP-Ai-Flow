import { describe, expect, it } from 'vitest'
import { buildExportFilename } from './export'

describe('buildExportFilename', () => {
  const exportedAt = new Date(2026, 7, 8, 9, 5)

  it('adds the local export timestamp required by the file naming convention', () => {
    expect(buildExportFilename('订单履行流程', 'svg', exportedAt)).toBe(
      '订单履行流程-20260808-0905.svg',
    )
  })

  it('replaces unsafe filename characters and handles a blank title', () => {
    expect(buildExportFilename('订单/审批: 主流程', 'json', exportedAt)).toBe(
      '订单-审批- 主流程-20260808-0905.json',
    )
    expect(buildExportFilename('  ', 'png', exportedAt)).toBe('flowchart-20260808-0905.png')
  })
})
