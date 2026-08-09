import { describe, expect, it } from 'vitest'
import { buildExportFilename, parseDownloadFilename } from './export'

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

describe('parseDownloadFilename', () => {
  it('prefers and decodes an RFC 5987 UTF-8 filename', () => {
    expect(
      parseDownloadFilename(
        'attachment; filename="SAP-Blueprint-process-r2.md"; '
          + "filename*=UTF-8''SAP-Blueprint-%E7%9B%B4%E6%8E%A5%E7%89%A9%E6%96%99-r2.md",
        'SAP-Blueprint.md',
      ),
    ).toBe('SAP-Blueprint-直接物料-r2.md')
  })

  it('supports a basic filename and rejects unsafe or malformed values', () => {
    expect(
      parseDownloadFilename(
        'attachment; filename="SAP-Blueprint-process-r2.docx"',
        'SAP-Blueprint.docx',
      ),
    ).toBe('SAP-Blueprint-process-r2.docx')
    expect(
      parseDownloadFilename(
        "attachment; filename*=UTF-8''..%2Fsecret.md",
        'SAP-Blueprint.md',
      ),
    ).toBe('..-secret.md')
    expect(
      parseDownloadFilename(
        "attachment; filename*=UTF-8''%E0%A4%A",
        'SAP-Blueprint.md',
      ),
    ).toBe('SAP-Blueprint.md')
  })
})
