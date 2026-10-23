import { useState } from 'react'
import { Loader2, Play } from 'lucide-react'
import { getErrorMessage } from '../../api/client'
import { getPlaybackInfo } from '../../api/endpoints'

// Playback links expire after 5 minutes, so we fetch a fresh one on click.
export default function AudioPlayer({ recordingId }: { recordingId: number }) {
  const [state, setState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setState('loading')
    setError(null)
    try {
      const info = await getPlaybackInfo(recordingId)
      setUrl(info.playback_url)
      setState('ready')
    } catch (err) {
      setError(getErrorMessage(err))
      setState('error')
    }
  }

  if (state === 'ready' && url) {
    return (
      <audio
        controls
        autoPlay
        src={url}
        className="w-full"
        onError={() => {
          setError('The audio link expired or could not be played. Try again.')
          setState('error')
        }}
      />
    )
  }

  return (
    <div>
      <button
        type="button"
        onClick={load}
        disabled={state === 'loading'}
        className="inline-flex h-11 items-center gap-2 rounded-md border border-line px-5 text-sm font-medium transition-colors hover:border-ink disabled:opacity-60"
      >
        {state === 'loading' ? (
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
        ) : (
          <Play size={16} aria-hidden="true" />
        )}
        {state === 'loading' ? 'Loading audio…' : 'Play recording'}
      </button>
      {error && <p className="mt-3 text-sm text-danger">{error}</p>}
    </div>
  )
}