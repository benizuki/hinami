import { ref, type Ref } from "vue"
import { streamSpeech, synthesizeSpeech, transcribeAudio } from "../../api/hinami"
import { useSpeechPreferences } from "./useSpeechPreferences"

export function useVoice(response: Ref<string>) {
  const isVoiceListening = ref(false)
  const isVoiceTranscribing = ref(false)
  const isAiSpeaking = ref(false)
  const voicePlaybackEnabled = ref(true)
  const voiceStatus = ref("")
  const voiceError = ref("")

const voiceInputSupported = 'mediaDevices' in navigator && 'MediaRecorder' in window
const browserSpeechOutputSupported = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window
const streamingSpeechOutputSupported = 'AudioContext' in window && 'ReadableStream' in window
void browserSpeechOutputSupported
const voiceOutputSupported = 'Audio' in window
let voiceMediaRecorder: MediaRecorder | null = null
let voiceMediaStream: MediaStream | null = null
let voiceAudioChunks: BlobPart[] = []
let voiceInputBaseText = ''
let voiceRecordingStartedAt = 0
let aiSpeechAudio: HTMLAudioElement | null = null
let aiSpeechObjectUrl = ''
let aiSpeechAudioContext: AudioContext | null = null
let aiSpeechBufferSource: AudioBufferSourceNode | null = null
const aiSpeechScheduledSources = new Set<AudioBufferSourceNode>()
let aiSpeechAbortController: AbortController | null = null
let aiSpeechRequestId = 0
const aiSpeechCache = new Map<string, Blob>()
const aiSpeechPendingRequests = new Map<string, Promise<Blob>>()
const { preferencesVersion } = useSpeechPreferences()

function stopAiSpeech() {
  aiSpeechRequestId += 1
  aiSpeechAbortController?.abort()
  aiSpeechAbortController = null
  if (aiSpeechBufferSource) {
    try {
      aiSpeechBufferSource.stop()
    } catch {
      // The source may already have ended.
    }
    aiSpeechBufferSource.disconnect()
    aiSpeechBufferSource = null
  }
  clearScheduledSpeechSources()
  if (aiSpeechAudio) {
    aiSpeechAudio.pause()
    aiSpeechAudio.removeAttribute('src')
    aiSpeechAudio.load()
    aiSpeechAudio = null
  }
  if (aiSpeechObjectUrl) {
    URL.revokeObjectURL(aiSpeechObjectUrl)
    aiSpeechObjectUrl = ''
  }
  if (browserSpeechOutputSupported) window.speechSynthesis.cancel()
  isAiSpeaking.value = false
}

function clearScheduledSpeechSources() {
  aiSpeechScheduledSources.forEach((source) => {
    try {
      source.stop()
    } catch {
      // The source may already have ended.
    }
    source.disconnect()
  })
  aiSpeechScheduledSources.clear()
}

function unlockAiAudio() {
  if (!('AudioContext' in window)) return
  if (!aiSpeechAudioContext) aiSpeechAudioContext = new AudioContext()
  if (aiSpeechAudioContext.state === 'suspended') void aiSpeechAudioContext.resume()
}

function normalizeSpeechText(text: string) {
  return text
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/[`*_#>-]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

function extractUserFacingSpeechText(text: string) {
  const trimmed = text.trim()

  // 応答全体がJSONとして返ってきた場合も、利用者向けのreplyだけを読む。
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    try {
      const parsed: unknown = JSON.parse(trimmed)
      if (typeof parsed === 'object' && parsed !== null && 'reply' in parsed) {
        const reply = (parsed as { reply?: unknown }).reply
        if (typeof reply === 'string' && reply.trim()) return reply.trim()
      }
    } catch {
      // 通常の文章として後続の除外処理を続ける。
    }
  }

  // Geminiがまれにreplyへ内部向けの指示・推論を続けてしまう場合、そこから後ろは読み上げない。
  const internalSectionPattern = /(?:^|\s)(?:(?:内部(?:メモ|指示|注意事項)|(?:LLM|AI)への注意事項|システム(?:指示|メッセージ)|重要なルール|出力JSON|推論|判断・例外(?:フェーズ)?の(?:注意事項|指示|ルール))\s*[：:]|(?:fragment_action|session_state|completion_score|missing_items|next_stage|is_complete)\s*[=:：])/i
  const match = internalSectionPattern.exec(trimmed)
  return match && typeof match.index === 'number'
    ? trimmed.slice(0, match.index).trim()
    : trimmed
}

function sentenceParts(text: string) {
  return normalizeSpeechText(text).match(/[^。！？!?]+[。！？!?]?/g)?.map((part) => part.trim()).filter(Boolean) ?? []
}

function isSummaryWithNumberedItems(text: string) {
  return (text.match(/(?:^|\s)\d+[.．)）]\s*/g) ?? []).length >= 3
}

function speechTextForAiMessage(text: string) {
  const normalized = normalizeSpeechText(extractUserFacingSpeechText(text))
  const sentences = sentenceParts(normalized)
  let questionIndex = -1
  for (let index = sentences.length - 1; index >= 0; index -= 1) {
    if (/[？?]$/.test(sentences[index])) {
      questionIndex = index
      break
    }
  }
  if (questionIndex >= 0 && isSummaryWithNumberedItems(normalized)) {
    return sentences[questionIndex]
  }
  if (normalized.length <= 220) return normalized
  const selected = questionIndex >= 0
    ? sentences.slice(Math.max(0, questionIndex - 1), questionIndex + 1)
    : sentences.slice(-2)
  const compact = selected.join(' ')
  return compact.length <= 260 ? compact : `${compact.slice(0, 257)}…`
}

// 分けた塊はそれぞれ別に生成され、声の質感が塊ごとに揺れる。サーバーの上限（4,000バイト）に
// 収まる範囲で、なるべく1回で生成する。
const SPEECH_CHUNK_MAX_CHARS = 1000

function splitSpeechText(text: string) {
  const sentences = sentenceParts(text)
  const chunks: string[] = []
  let current = ''
  sentences.forEach((sentence) => {
    const next = current ? `${current} ${sentence}` : sentence
    if (next.length > SPEECH_CHUNK_MAX_CHARS && current) {
      chunks.push(current)
      current = sentence
    } else {
      current = next
    }
  })
  if (current) chunks.push(current)
  return chunks.length ? chunks : [text]
}

function rememberSpeechBlob(text: string, blob: Blob) {
  if (aiSpeechCache.size >= 48) {
    const oldestKey = aiSpeechCache.keys().next().value
    if (typeof oldestKey === 'string') aiSpeechCache.delete(oldestKey)
  }
  aiSpeechCache.set(text, blob)
}

async function getSpeechBlob(text: string, signal: AbortSignal) {
  // 声やトーンを変えたら、同じ文章でも作り直す。
  const key = `${preferencesVersion.value}\n${text}`
  const cached = aiSpeechCache.get(key)
  if (cached) return cached
  const pending = aiSpeechPendingRequests.get(key)
  if (pending) return pending
  const request = synthesizeSpeech(text, signal)
    .then((blob) => {
      rememberSpeechBlob(key, blob)
      return blob
    })
    .finally(() => aiSpeechPendingRequests.delete(key))
  aiSpeechPendingRequests.set(key, request)
  return request
}

async function playSpeechBlob(audioBlob: Blob, requestId: number) {
  if (requestId !== aiSpeechRequestId) return
  if (aiSpeechAudioContext?.state === 'running') {
    const audioBuffer = await aiSpeechAudioContext.decodeAudioData(await audioBlob.arrayBuffer())
    if (requestId !== aiSpeechRequestId) return
    await new Promise<void>((resolve) => {
      const source = aiSpeechAudioContext!.createBufferSource()
      source.buffer = audioBuffer
      source.connect(aiSpeechAudioContext!.destination)
      aiSpeechBufferSource = source
      source.onended = () => {
        if (aiSpeechBufferSource === source) aiSpeechBufferSource = null
        resolve()
      }
      source.start()
    })
    return
  }
  await new Promise<void>((resolve, reject) => {
    const objectUrl = URL.createObjectURL(audioBlob)
    aiSpeechObjectUrl = objectUrl
    const audio = new Audio(objectUrl)
    aiSpeechAudio = audio
    audio.onended = () => {
      if (aiSpeechAudio === audio) aiSpeechAudio = null
      URL.revokeObjectURL(objectUrl)
      if (aiSpeechObjectUrl === objectUrl) aiSpeechObjectUrl = ''
      resolve()
    }
    audio.onerror = () => {
      if (aiSpeechAudio === audio) aiSpeechAudio = null
      URL.revokeObjectURL(objectUrl)
      if (aiSpeechObjectUrl === objectUrl) aiSpeechObjectUrl = ''
      reject(new Error('Gemini音声を再生できませんでした。'))
    }
    audio.play().catch(reject)
  })
}

async function playSpeechPcmStream(
  stream: ReadableStream<Uint8Array>,
  sampleRate: number,
  requestId: number,
  signal: AbortSignal,
) {
  const audioContext = aiSpeechAudioContext
  if (!audioContext) throw new Error('ストリーミング音声を再生できないブラウザです。')
  if (audioContext.state === 'suspended') await audioContext.resume()

  const reader = stream.getReader()
  let remainder = new Uint8Array()
  let scheduledAt = audioContext.currentTime + 0.08
  let lastSourceEnded: Promise<void> = Promise.resolve()
  let receivedAudio = false
  try {
    while (!signal.aborted && requestId === aiSpeechRequestId) {
      const { value, done } = await reader.read()
      if (done) break
      if (!value?.byteLength) continue

      const bytes = new Uint8Array(remainder.byteLength + value.byteLength)
      bytes.set(remainder)
      bytes.set(value, remainder.byteLength)
      const usableBytes = bytes.byteLength - (bytes.byteLength % 2)
      remainder = bytes.slice(usableBytes)
      if (!usableBytes) continue

      const sampleCount = usableBytes / 2
      const audioBuffer = audioContext.createBuffer(1, sampleCount, sampleRate)
      const channel = audioBuffer.getChannelData(0)
      const view = new DataView(bytes.buffer, bytes.byteOffset, usableBytes)
      for (let index = 0; index < sampleCount; index += 1) {
        channel[index] = view.getInt16(index * 2, true) / 32768
      }

      const source = audioContext.createBufferSource()
      source.buffer = audioBuffer
      source.connect(audioContext.destination)
      aiSpeechScheduledSources.add(source)
      scheduledAt = Math.max(scheduledAt, audioContext.currentTime + 0.04)
      lastSourceEnded = new Promise<void>((resolve) => {
        source.onended = () => {
          aiSpeechScheduledSources.delete(source)
          source.disconnect()
          resolve()
        }
      })
      source.start(scheduledAt)
      scheduledAt += audioBuffer.duration
      if (!receivedAudio) {
        receivedAudio = true
        voiceStatus.value = 'Geminiの自然音声をストリーミング再生しています'
      }
    }
    if (signal.aborted || requestId !== aiSpeechRequestId) return
    if (!receivedAudio) throw new Error('Gemini-TTSから音声データを受信できませんでした。')
    await lastSourceEnded
  } finally {
    if (signal.aborted) await reader.cancel().catch(() => undefined)
    reader.releaseLock()
  }
}

async function playBufferedSpeechFallback(text: string, requestId: number, controller: AbortController) {
  const speechChunks = splitSpeechText(text)
  voiceStatus.value = speechChunks.length > 1 ? 'Geminiが音声を分割生成しています' : 'Geminiが自然な音声を生成しています'
  let nextBlob = getSpeechBlob(speechChunks[0], controller.signal)
  for (let index = 0; index < speechChunks.length; index += 1) {
    const audioBlob = await nextBlob
    if (requestId !== aiSpeechRequestId || controller.signal.aborted) return
    nextBlob = speechChunks[index + 1] ? getSpeechBlob(speechChunks[index + 1], controller.signal) : Promise.resolve(new Blob())
    voiceStatus.value = 'Geminiの自然音声で読み上げています'
    await playSpeechBlob(audioBlob, requestId)
  }
}

function speakWithBrowserVoice(text: string, requestId: number) {
  if (!browserSpeechOutputSupported || requestId !== aiSpeechRequestId) {
    isAiSpeaking.value = false
    voiceStatus.value = ''
    voiceError.value = 'AI質問を読み上げられませんでした。'
    return
  }
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ja-JP'
  utterance.rate = 1
  const japaneseVoice = window.speechSynthesis.getVoices().find((voice) => voice.lang.toLowerCase().startsWith('ja'))
  if (japaneseVoice) utterance.voice = japaneseVoice
  utterance.onstart = () => {
    if (requestId !== aiSpeechRequestId) return
    isAiSpeaking.value = true
    voiceStatus.value = 'ブラウザ音声で読み上げています'
  }
  utterance.onend = () => {
    if (requestId !== aiSpeechRequestId) return
    isAiSpeaking.value = false
    voiceStatus.value = ''
  }
  utterance.onerror = () => {
    if (requestId !== aiSpeechRequestId) return
    isAiSpeaking.value = false
    voiceStatus.value = ''
    voiceError.value = 'AI質問を読み上げられませんでした。'
  }
  window.speechSynthesis.speak(utterance)
}

async function speakAiMessage(text: string, force = false) {
  if (!voiceOutputSupported || (!voicePlaybackEnabled.value && !force)) return
  unlockAiAudio()
  stopAiSpeech()
  const requestId = aiSpeechRequestId
  voiceError.value = ''
  const speechText = speechTextForAiMessage(text)
  if (!speechText) {
    isAiSpeaking.value = false
    voiceStatus.value = ''
    return
  }
  voiceStatus.value = 'Geminiのストリーミング音声を準備しています'
  isAiSpeaking.value = true
  const controller = new AbortController()
  aiSpeechAbortController = controller
  try {
    if (!streamingSpeechOutputSupported) {
      await playBufferedSpeechFallback(speechText, requestId, controller)
    } else {
      try {
        const streamedAudio = await streamSpeech(speechText, controller.signal)
        await playSpeechPcmStream(
          streamedAudio.stream,
          streamedAudio.sampleRate,
          requestId,
          controller.signal,
        )
      } catch (streamError) {
        if (controller.signal.aborted || requestId !== aiSpeechRequestId) return
        // 利用上限に達しているときは、別経路で呼び直しても同じく断られ、上限を余計に使うだけになる。
        if ((streamError as { status?: number }).status === 429) throw streamError
        console.warn('Gemini-TTS streaming fell back to buffered playback', streamError)
        clearScheduledSpeechSources()
        voiceStatus.value = '標準のGemini音声へ切り替えています'
        await playBufferedSpeechFallback(speechText, requestId, controller)
      }
    }
    if (requestId !== aiSpeechRequestId) return
    aiSpeechAbortController = null
    isAiSpeaking.value = false
    voiceStatus.value = ''
  } catch (error) {
    if (controller.signal.aborted || requestId !== aiSpeechRequestId) return
    aiSpeechAbortController = null
    isAiSpeaking.value = false
    voiceStatus.value = ''
    voiceError.value = error instanceof Error ? error.message : 'Gemini音声を生成できませんでした。'
  }
}

function toggleVoicePlayback() {
  voicePlaybackEnabled.value = !voicePlaybackEnabled.value
  voiceError.value = ''
  if (voicePlaybackEnabled.value) unlockAiAudio()
  if (!voicePlaybackEnabled.value) stopAiSpeech()
}

function voiceCaptureErrorMessage(error: unknown) {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') return 'マイクの使用が許可されていません。アドレスバーのマイク権限を「許可」にしてください。'
    if (error.name === 'NotFoundError') return '利用できるマイクが見つかりません。マイクの接続を確認してください。'
    if (error.name === 'NotReadableError') return 'マイクを使用できません。ほかのアプリがマイクを使用していないか確認してください。'
  }
  return '音声入力を開始できませんでした。'
}

function voiceRecordingOptions(): MediaRecorderOptions | undefined {
  const mimeType = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ].find((candidate) => MediaRecorder.isTypeSupported(candidate))
  return mimeType ? { mimeType } : undefined
}

function isTimestampOnlyText(text: string) {
  return /^(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?$/.test(text.trim())
}

function releaseVoiceStream() {
  voiceMediaStream?.getTracks().forEach((track) => track.stop())
  voiceMediaStream = null
}

async function transcribeRecordedVoice(audio: Blob) {
  isVoiceTranscribing.value = true
  voiceStatus.value = 'Geminiが音声を文字起こししています'
  voiceError.value = ''
  try {
    const result = await transcribeAudio(audio)
    const transcript = result.transcript.trim()
    if (!transcript || isTimestampOnlyText(transcript)) {
      voiceStatus.value = ''
      voiceError.value = '発話内容を文字起こしできませんでした。録音時間ではなく、話した内容だけを入力します。もう一度お試しください。'
      response.value = voiceInputBaseText
      return
    }
    response.value = [voiceInputBaseText, transcript].filter(Boolean).join(' ')
    voiceStatus.value = '文字起こし完了。内容を確認して送信してください'
  } catch (error) {
    voiceStatus.value = ''
    voiceError.value = error instanceof Error ? error.message : '音声を文字起こしできませんでした。'
  } finally {
    isVoiceTranscribing.value = false
  }
}

async function startVoiceInput() {
  if (!voiceInputSupported) {
    voiceError.value = 'このブラウザは録音に対応していません。Chrome、Edge、Safariの最新版でお試しください。'
    return
  }
  if (!window.isSecureContext) {
    voiceError.value = '音声入力にはHTTPSまたはlocalhostでのアクセスが必要です。'
    return
  }
  stopAiSpeech()
  voiceError.value = ''
  voiceInputBaseText = response.value.trim()
  voiceAudioChunks = []
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    voiceMediaStream = stream
    const recorder = new MediaRecorder(stream, voiceRecordingOptions())
    voiceMediaRecorder = recorder
    recorder.ondataavailable = (event) => {
      if (event.data.size) voiceAudioChunks.push(event.data)
    }
    recorder.onerror = () => {
      voiceError.value = '録音中にエラーが発生しました。'
      isVoiceListening.value = false
      voiceStatus.value = ''
      releaseVoiceStream()
    }
    recorder.onstop = () => {
      const chunks = [...voiceAudioChunks]
      const mimeType = recorder.mimeType || 'audio/webm'
      const recordingDuration = Date.now() - voiceRecordingStartedAt
      voiceAudioChunks = []
      voiceMediaRecorder = null
      isVoiceListening.value = false
      releaseVoiceStream()
      if (recordingDuration < 800) voiceError.value = '録音が短すぎます。1秒以上話してから停止してください。'
      else if (chunks.length) void transcribeRecordedVoice(new Blob(chunks, { type: mimeType }))
      else voiceError.value = '音声が録音されませんでした。もう一度お試しください。'
    }
    voiceRecordingStartedAt = Date.now()
    recorder.start(250)
    isVoiceListening.value = true
    voiceStatus.value = '録音中です。話し終えたら停止してください'
  } catch (error) {
    voiceMediaRecorder = null
    releaseVoiceStream()
    voiceError.value = voiceCaptureErrorMessage(error)
  }
}

function stopVoiceInput() {
  if (!voiceMediaRecorder || voiceMediaRecorder.state === 'inactive') return
  voiceStatus.value = '録音を停止しています'
  voiceMediaRecorder.stop()
}

function cancelVoiceInput() {
  const recorder = voiceMediaRecorder
  if (recorder) {
    recorder.ondataavailable = null
    recorder.onstop = null
    recorder.onerror = null
    if (recorder.state !== 'inactive') recorder.stop()
  }
  voiceMediaRecorder = null
  voiceAudioChunks = []
  voiceRecordingStartedAt = 0
  isVoiceListening.value = false
  isVoiceTranscribing.value = false
  releaseVoiceStream()
}

function toggleVoiceInput() {
  if (isVoiceListening.value) stopVoiceInput()
  else void startVoiceInput()
}

  return {
    voiceInputSupported,
    voiceOutputSupported,
    isVoiceListening,
    isVoiceTranscribing,
    isAiSpeaking,
    voicePlaybackEnabled,
    voiceStatus,
    voiceError,
    stopAiSpeech,
    unlockAiAudio,
    speakAiMessage,
    toggleVoicePlayback,
    isTimestampOnlyText,
    startVoiceInput,
    stopVoiceInput,
    cancelVoiceInput,
    toggleVoiceInput,
  }
}
