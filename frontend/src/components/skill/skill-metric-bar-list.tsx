'use client'

/**
 * Phase 3 评估指标条形列表 — 与 usage `SpendBarChart` 相同的 plain-div 条形
 * 模式（数据驱动 width 行内样式，check-design-system.mjs allowlist）。
 * A/B 基准比较与按版本通过率趋势共享使用。
 */

export type SkillMetricBarRow = {
  readonly key: string
  readonly label: string
  /** 0..1 — bar fill ratio. */
  readonly ratio: number
  readonly display: string
  readonly tone: 'primary' | 'baseline'
  readonly meta?: string | null
}

function clampRatio(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.max(0, Math.min(1, value))
}

export function SkillMetricBarList({
  rows,
  testId,
}: {
  readonly rows: readonly SkillMetricBarRow[]
  readonly testId?: string
}) {
  return (
    <div className="space-y-2" data-testid={testId}>
      {rows.map((row) => {
        const widthPct = Math.max(2, clampRatio(row.ratio) * 100)
        return (
          <div key={row.key} className="flex items-center gap-2" data-testid="skill-metric-bar">
            <span
              className="w-32 shrink-0 truncate moldy-ui-caption text-foreground/80"
              title={row.label}
            >
              {row.label}
            </span>
            <div className="relative h-5 flex-1 overflow-hidden rounded-md bg-muted/40">
              <div
                className="moldy-usage-bar h-full rounded-md transition-[width]"
                data-usage-metric={row.tone === 'primary' ? 'tokens' : 'baseline'}
                style={{ width: `${widthPct}%` }}
              />
            </div>
            <span className="w-24 shrink-0 text-right font-mono moldy-ui-caption tabular-nums text-foreground/90">
              {row.display}
            </span>
            {row.meta ? (
              <span className="w-20 shrink-0 truncate text-right moldy-ui-micro text-muted-foreground">
                {row.meta}
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
