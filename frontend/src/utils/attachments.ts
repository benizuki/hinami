import type { LlmInterviewAttachment } from '../api/hinami'

export const supportedInterviewAttachmentTypes = new Set<LlmInterviewAttachment['mime_type']>([
  'image/png',
  'image/jpeg',
  'image/webp',
  'application/pdf',
])

export const interviewAttachmentMaxBytes = 8 * 1024 * 1024
export const interviewAttachmentTotalMaxBytes = 20 * 1024 * 1024

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error(`${file.name}を読み込めませんでした`))
    reader.readAsDataURL(file)
  })
}
