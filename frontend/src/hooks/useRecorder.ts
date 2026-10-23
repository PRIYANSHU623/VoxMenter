import { useCallback, useEffect, useRef, useState } from 'react'

export type RecorderStatus =
  | 'idle'
  | 'requesting' // waiting for the user to allow the microphone
  | 'recording'
  | 'recorded'
  | 'error'

// Formats your backend accepts: webm, mp4/m4a, ogg, wav, mp3.
// Chrome/Firefox/Edge produce webm or ogg, Safari produces mp4.
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
]

function pickMimeType(): string | undefined {
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type))
}

export function isRecordingSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  )
}

function describeError(error: unknown): string {
  if (error instanceof DOMException) {
    switch (error.name) {
      case 'NotAllowedError':
      case 'SecurityError':
        return 'Microphone access was blocked. Allow it from the lock icon in your browser’s address bar, then try again.'
      case 'NotFoundError':
        return 'No microphone was found. Connect one and try again.'
      case 'NotReadableError':
        return 'Your microphone is being used by another app. Close it and try again.'
    }
  }
  return 'Could not start recording. Please try again.'
}

export function useRecorder(maxSeconds = 300) {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [seconds, setSeconds] = useState(0)
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const [audioUrl, setAudioUrl] = useState<string | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const startedAtRef = useRef(0)
  const urlRef = useRef<string | null>(null)
  const busyRef = useRef(false)
  const mountedRef = useRef(false)

  // Stops the timer, the recorder and the microphone.
  const teardown = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    const recorder = recorderRef.current
    if (recorder) {
      recorder.ondataavailable = null
      recorder.onstop = null
      recorder.onerror = null
      if (recorder.state !== 'inactive') recorder.stop()
      recorderRef.current = null
    }
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }, [])

  const revokeUrl = useCallback(() => {
    if (urlRef.current) {
      URL.revokeObjectURL(urlRef.current)
      urlRef.current = null
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      teardown()
      revokeUrl()
    }
  }, [teardown, revokeUrl])

  const fail = useCallback(
    (message: string) => {
      teardown()
      busyRef.current = false
      setError(message)
      setStatus('error')
    },
    [teardown],
  )

  const start = useCallback(async () => {
    if (busyRef.current) return
    if (!isRecordingSupported()) {
      setError('Audio recording is not supported in this browser. Try a recent Chrome, Edge, Firefox or Safari.')
      setStatus('error')
      return
    }

    busyRef.current = true
    revokeUrl()
    setAudioBlob(null)
    setAudioUrl(null)
    setSeconds(0)
    setError(null)
    setStatus('requesting')

    let stream: MediaStream
    try {
      // The microphone is only requested here, after the user clicks.
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (err) {
      if (mountedRef.current) fail(describeError(err))
      return
    }

    // The user left the page while the permission prompt was open.
    if (!mountedRef.current) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }

    try {
      const mimeType = pickMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)

      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }

      recorder.onerror = () => fail('The recording failed. Please try again.')

      recorder.onstop = () => {
        const type = recorder.mimeType || mimeType || 'audio/webm'
        const blob = new Blob(chunksRef.current, { type })
        const elapsed = Math.round((Date.now() - startedAtRef.current) / 1000)
        teardown()
        busyRef.current = false

        if (blob.size === 0) {
          setError('Nothing was recorded. Check your microphone and try again.')
          setStatus('error')
          return
        }

        const url = URL.createObjectURL(blob)
        urlRef.current = url
        setSeconds(elapsed)
        setAudioBlob(blob)
        setAudioUrl(url)
        setStatus('recorded')
      }

      recorder.start()
      startedAtRef.current = Date.now()
      setStatus('recording')

      timerRef.current = window.setInterval(() => {
        const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000)
        setSeconds(elapsed)
        if (elapsed >= maxSeconds && recorder.state === 'recording') {
          recorder.stop() // auto-stop at the time limit
        }
      }, 250)
    } catch {
      fail('Could not start recording. Please try again.')
    }
  }, [fail, maxSeconds, revokeUrl, teardown])

  const stop = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state === 'recording') recorder.stop()
  }, [])

  // Throws away the current take so the user can record again.
  const reset = useCallback(() => {
    teardown()
    revokeUrl()
    busyRef.current = false
    setAudioBlob(null)
    setAudioUrl(null)
    setSeconds(0)
    setError(null)
    setStatus('idle')
  }, [revokeUrl, teardown])

  return {
    status,
    error,
    seconds,
    audioBlob,
    audioUrl,
    supported: isRecordingSupported(),
    maxSeconds,
    start,
    stop,
    reset,
  }
}