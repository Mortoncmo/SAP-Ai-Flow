export type ExportFormat = 'json' | 'png' | 'svg'

export function buildExportFilename(
  title: string,
  format: ExportFormat,
  exportedAt = new Date(),
): string {
  const safeTitle = title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
  const date = [
    exportedAt.getFullYear(),
    pad(exportedAt.getMonth() + 1),
    pad(exportedAt.getDate()),
  ].join('')
  const time = [pad(exportedAt.getHours()), pad(exportedAt.getMinutes())].join('')

  return `${safeTitle || 'flowchart'}-${date}-${time}.${format}`
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  downloadUrl(url, filename)
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function downloadUrl(url: string, filename: string) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}
