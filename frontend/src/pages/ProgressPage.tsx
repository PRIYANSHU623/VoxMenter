import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAttempts } from '../hooks/useAttempts'
import type { Attempt } from '../hooks/useAttempts'
import { formatDate } from '../utils/formatDate'
import { CATEGORY_KEYS, CATEGORY_SCORE_LABELS, categoryLabel } from '../utils/labels'

// ---------- helpers ----------
function show(value: number | null | undefined): string {
  return typeof value === 'number' ? String(Math.round(value)) : '—'
}

function average(values: number[]): number | null {
  return values.length === 0 ? null : values.reduce((sum, v) => sum + v, 0) / values.length
}

function numbers(values: (number | null | undefined)[]): number[] {
  return values.filter((v): v is number => typeof v === 'number')
}

function Change({ first, last }: { first: number | null; last: number | null }) {
  if (first === null || last === null) return <span className="text-muted">—</span>
  const delta = Math.round(last - first)
  if (delta === 0) return <span className="text-muted">no change</span>
  return (
    <span className={delta > 0 ? 'text-ok' : 'text-danger'}>
      {delta > 0 ? '+' : ''}
      {delta} since your first attempt
    </span>
  )
}

// ---------- chart ----------
const W = 480
const H = 260
const PAD = { left: 34, right: 14, top: 14, bottom: 30 }
const GRID = [0, 25, 50, 75, 100]

function TrendChart({ points }: { points: Attempt[] }) {
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  const count = points.length

  const x = (index: number) =>
    PAD.left + (count === 1 ? innerW / 2 : (index / (count - 1)) * innerW)
  const y = (value: number) => PAD.top + innerH * (1 - Math.max(0, Math.min(100, value)) / 100)

  function series(pick: (a: Attempt) => number | null | undefined) {
    const dots = points
      .map((attempt, index) => ({ index, value: pick(attempt), attempt }))
      .filter((p): p is { index: number; value: number; attempt: Attempt } => typeof p.value === 'number')
    const path = dots.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.index).toFixed(1)} ${y(p.value).toFixed(1)}`).join(' ')
    return { dots, path }
  }

  const tech = series((a) => a.evaluation?.technical_score)
  const comm = series((a) => a.evaluation?.communication_score)

  // Show at most ~6 x labels so they never collide.
  const step = Math.max(1, Math.ceil(count / 6))

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Line chart of technical and communication scores across your evaluated attempts"
      className="h-auto w-full"
    >
      {GRID.map((g) => (
        <g key={g}>
          <line x1={PAD.left} x2={W - PAD.right} y1={y(g)} y2={y(g)} className="stroke-line" strokeWidth={1} />
          <text x={PAD.left - 8} y={y(g) + 4} textAnchor="end" fontSize={11} className="fill-muted">
            {g}
          </text>
        </g>
      ))}

      {points.map((_, index) =>
        index % step === 0 || index === count - 1 ? (
          <text key={index} x={x(index)} y={H - 8} textAnchor="middle" fontSize={11} className="fill-muted">
            #{index + 1}
          </text>
        ) : null,
      )}

      <path d={tech.path} fill="none" className="stroke-tech" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <path d={comm.path} fill="none" className="stroke-comm" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />

      {tech.dots.map((p) => (
        <circle key={`t${p.index}`} cx={x(p.index)} cy={y(p.value)} r={4} className="fill-tech">
          <title>{`Technical ${Math.round(p.value)} · ${formatDate(p.attempt.evaluation?.created_at ?? '')}`}</title>
        </circle>
      ))}
      {comm.dots.map((p) => (
        <circle key={`c${p.index}`} cx={x(p.index)} cy={y(p.value)} r={4} className="fill-comm">
          <title>{`Communication ${Math.round(p.value)} · ${formatDate(p.attempt.evaluation?.created_at ?? '')}`}</title>
        </circle>
      ))}
    </svg>
  )
}

// ---------- page ----------
export default function ProgressPage() {
  const { attempts, loading, error, reload } = useAttempts()
  const [category, setCategory] = useState('all')

  // Evaluated attempts, oldest first, so charts read left to right.
  const evaluated = useMemo(
    () =>
      attempts
        .filter((a) => a.evaluation)
        .sort((a, b) => (a.evaluation?.created_at ?? '').localeCompare(b.evaluation?.created_at ?? '')),
    [attempts],
  )

  const categories = useMemo(
    () => [...new Set(evaluated.map((a) => a.question?.category).filter((c): c is string => !!c))].sort(),
    [evaluated],
  )

  const points = evaluated.filter((a) => category === 'all' || a.question?.category === category)

  const technical = numbers(points.map((a) => a.evaluation?.technical_score))
  const communication = numbers(points.map((a) => a.evaluation?.communication_score))

  const categoryStats = CATEGORY_KEYS.map((key) => {
    const values = numbers(points.map((a) => a.evaluation?.report?.scores?.[key]?.score))
    return {
      key,
      average: average(values),
      first: values.length >= 2 ? values[0] : null,
      last: values.length >= 2 ? values[values.length - 1] : null,
      count: values.length,
    }
  })

  const ranked = categoryStats.filter((c) => c.average !== null).sort((a, b) => (b.average ?? 0) - (a.average ?? 0))
  const strongest = ranked[0]
  const weakest = ranked.length > 1 ? ranked[ranked.length - 1] : undefined

  return (
    <div>
      <p className="eyebrow">Progress</p>
      <h1 className="mt-2 text-3xl font-semibold">How you’re improving</h1>
      <p className="mt-2 max-w-xl text-muted">
        Trends from your evaluated answers. Nothing here is estimated: every point is a saved evaluation.
      </p>

      {loading && (
        <div className="flex justify-center py-24 text-muted">
          <Loader2 className="animate-spin" aria-label="Loading progress" />
        </div>
      )}

      {!loading && error && (
        <div className="mt-10">
          <p className="text-danger">{error}</p>
          <button
            type="button"
            onClick={reload}
            className="mt-4 h-11 rounded-md border border-line px-4 text-sm hover:bg-surface"
          >
            Try again
          </button>
        </div>
      )}

      {!loading && !error && evaluated.length < 2 && (
        <div className="mt-12 border-y border-line py-12">
          <p className="font-display text-2xl">Not enough history yet</p>
          <p className="mt-3 max-w-lg text-muted">
            {evaluated.length === 0
              ? 'Complete an evaluation to start your progress chart.'
              : 'You have one evaluated answer. Complete one more and your trend will appear here.'}
          </p>
          <Link
            to="/practice"
            className="mt-6 inline-flex h-11 items-center rounded-md bg-accent px-5 text-sm font-medium text-accent-fg hover:bg-accent-hover"
          >
            Practice a question
          </Link>
        </div>
      )}

      {!loading && !error && evaluated.length >= 2 && (
        <>
          {categories.length > 1 && (
            <div className="mt-8">
              <p className="eyebrow mb-2">Category</p>
              <div className="flex flex-wrap gap-2">
                {['all', ...categories].map((c) => (
                  <button
                    key={c}
                    type="button"
                    aria-pressed={category === c}
                    onClick={() => setCategory(c)}
                    className={[
                      'min-h-9 rounded-full border px-4 text-sm transition-colors',
                      category === c
                        ? 'border-ink bg-ink text-canvas'
                        : 'border-line text-muted hover:border-ink hover:text-ink',
                    ].join(' ')}
                  >
                    {c === 'all' ? 'All' : categoryLabel(c)}
                  </button>
                ))}
              </div>
            </div>
          )}

          {points.length < 2 ? (
            <div className="mt-10 border-t border-line py-10">
              <p className="font-display text-xl">Only {points.length} evaluated answer in this category</p>
              <p className="mt-2 text-muted">A trend needs at least two. Pick “All” or practice more here.</p>
            </div>
          ) : (
            <>
              {/* ---------- Summary ---------- */}
              <section
                aria-label="Summary"
                className="mt-10 grid divide-y divide-line border-y border-line sm:grid-cols-3 sm:divide-x sm:divide-y-0"
              >
                <div className="py-6 sm:pr-6">
                  <p className="eyebrow text-tech">Technical average</p>
                  <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-tech">
                    {show(average(technical))}
                  </p>
                  <p className="mt-2 text-xs">
                    <Change first={technical[0] ?? null} last={technical[technical.length - 1] ?? null} />
                  </p>
                </div>
                <div className="py-6 sm:px-6">
                  <p className="eyebrow text-comm">Communication average</p>
                  <p className="mt-2 font-display text-5xl font-semibold tabular-nums text-comm">
                    {show(average(communication))}
                  </p>
                  <p className="mt-2 text-xs">
                    <Change first={communication[0] ?? null} last={communication[communication.length - 1] ?? null} />
                  </p>
                </div>
                <div className="py-6 sm:pl-6">
                  <p className="eyebrow">Evaluated answers</p>
                  <p className="mt-2 font-display text-5xl font-semibold tabular-nums">{points.length}</p>
                  <p className="mt-2 text-xs text-muted">
                    Best: {show(technical.length ? Math.max(...technical) : null)} tech,{' '}
                    {show(communication.length ? Math.max(...communication) : null)} comm
                  </p>
                </div>
              </section>

              {/* ---------- Chart ---------- */}
              <section className="mt-14" aria-label="Score trend">
                <h2 className="text-2xl font-semibold">Score trend</h2>
                <div className="mt-3 flex gap-6 text-sm">
                  <span className="flex items-center gap-2 text-tech">
                    <span aria-hidden="true" className="h-1 w-5 rounded-full bg-tech" /> Technical
                  </span>
                  <span className="flex items-center gap-2 text-comm">
                    <span aria-hidden="true" className="h-1 w-5 rounded-full bg-comm" /> Communication
                  </span>
                </div>
                <div className="mt-4 max-w-3xl">
                  <TrendChart points={points} />
                </div>
                <p className="mt-2 text-xs text-muted">
                  Each point is one evaluated answer, oldest on the left. Numbers match the list below.
                </p>
              </section>

              {/* ---------- Categories ---------- */}
              <section className="mt-14" aria-label="Category breakdown">
                <h2 className="text-2xl font-semibold">By category</h2>
                {strongest && weakest && (
                  <p className="mt-2 max-w-2xl text-sm text-muted">
                    Strongest: <span className="text-ink">{CATEGORY_SCORE_LABELS[strongest.key]}</span> ({show(strongest.average)}).
                    Needs the most work: <span className="text-ink">{CATEGORY_SCORE_LABELS[weakest.key]}</span> ({show(weakest.average)}).
                  </p>
                )}
                <div className="mt-5 divide-y divide-line border-y border-line">
                  {categoryStats.map((c) =>
                    c.average === null ? null : (
                      <div key={c.key} className="py-4">
                        <div className="flex items-baseline justify-between gap-4 text-sm">
                          <span className="font-medium">{CATEGORY_SCORE_LABELS[c.key]}</span>
                          <span className="font-mono tabular-nums">{show(c.average)}</span>
                        </div>
                        <div
                          role="img"
                          aria-label={`Average ${show(c.average)} out of 100`}
                          className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line"
                        >
                          <div className="h-full rounded-full bg-ink/70" style={{ width: `${c.average}%` }} />
                        </div>
                        <p className="mt-2 text-xs">
                          <Change first={c.first} last={c.last} />
                        </p>
                      </div>
                    ),
                  )}
                </div>
              </section>

              {/* ---------- All evaluated attempts ---------- */}
              <section className="mt-14" aria-label="Evaluated answers">
                <h2 className="text-2xl font-semibold">Every evaluated answer</h2>
                <ul className="mt-5 border-t border-line">
                  {[...points].reverse().map((attempt) => {
                    const number = points.indexOf(attempt) + 1
                    return (
                      <li key={attempt.session.id} className="border-b border-line">
                        <Link
                          to={`/review/${attempt.session.id}`}
                          className="flex flex-col gap-2 py-4 transition-colors hover:bg-surface sm:flex-row sm:items-center sm:justify-between sm:px-3"
                        >
                          <div className="min-w-0">
                            <p className="eyebrow">
                              #{number} · {formatDate(attempt.evaluation?.created_at ?? '')}
                              {attempt.question && ` · ${categoryLabel(attempt.question.category)}`}
                            </p>
                            <p className="mt-1 truncate text-sm font-medium">
                              {attempt.question?.title ?? `Session ${attempt.session.id}`}
                            </p>
                          </div>
                          <div className="flex shrink-0 gap-6 text-sm">
                            <span className="font-mono tabular-nums text-tech">
                              <span className="eyebrow mr-2 text-tech">Tech</span>
                              {show(attempt.evaluation?.technical_score)}
                            </span>
                            <span className="font-mono tabular-nums text-comm">
                              <span className="eyebrow mr-2 text-comm">Comm</span>
                              {show(attempt.evaluation?.communication_score)}
                            </span>
                          </div>
                        </Link>
                      </li>
                    )
                  })}
                </ul>
              </section>
            </>
          )}
        </>
      )}
    </div>
  )
}