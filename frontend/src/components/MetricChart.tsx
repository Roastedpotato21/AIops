import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type Point = { time: string; value: number | null; quality: string }

function rangeLabel(points: Point[]) {
  if (!points.length) return 'Requested window'
  const format = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' })
  const end = points.at(-1)?.time ?? points[0].time
  return `${format.format(new Date(points[0].time))}–${format.format(new Date(end))}`
}

export function MetricChart({ title, unit, points, format = (value) => value.toFixed(1) }: { title: string; unit: string; points: Point[]; format?: (value: number) => string }) {
  const chartPoints = points.map((point) => ({
    ...point,
    plotted: point.quality === 'complete' ? point.value : null,
  }))
  const values = chartPoints.flatMap((point) => point.plotted === null ? [] : [point.plotted])
  const timeTick = (value: string) => new Intl.DateTimeFormat(undefined, {
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
  return <section className="chart-card" aria-label={`${title} chart`}>
    <div className="chart-heading"><div><h3>{title}</h3><span>{rangeLabel(points)} · {unit}</span></div><strong>{values.length ? `${format(values.at(-1) ?? 0)} ${unit}` : 'No data'}</strong></div>
    <div className="metric-chart" style={{ height: 225, marginTop: 15, width: '100%' }} role="img" aria-label={`${title}; missing and incomplete points are shown as gaps`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartPoints} margin={{ top: 16, right: 12, bottom: 4, left: 0 }}>
          <CartesianGrid stroke="#20323d" vertical={false} />
          <XAxis dataKey="time" tickFormatter={timeTick} stroke="#80919e" minTickGap={36} />
          <YAxis stroke="#80919e" width={48} domain={[0, 'auto']} />
          <Tooltip labelFormatter={(value) => new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(String(value)))} formatter={(value) => [`${format(Number(value))} ${unit}`, title]} contentStyle={{ background: '#07141a', border: '1px solid #20323d', borderRadius: 8 }} />
          <Line type="linear" dataKey="plotted" stroke="#39d7c4" strokeWidth={2} dot={false} activeDot={{ r: 4 }} connectNulls={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
    <p className="chart-note">Gaps represent missing, stale, or insufficient observations; values are not interpolated.</p>
  </section>
}
