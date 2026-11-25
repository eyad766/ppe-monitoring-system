import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertOctagon, AlertTriangle, Camera, CheckCircle2, Cpu, Trash2, Users, Wifi } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, fmtDateTime, fmtTime, pct } from '../api.js'
import { useLive } from '../live.jsx'
import { Card, CameraStatus, CameraStream, Empty, ErrorNote, Kpi, StatusBadge } from '../components.jsx'

const HELMET = '#e5484d'
const VEST = '#f5a524'
const PIE_COLORS = [HELMET, VEST, '#6e56cf', '#0091ff']

export default function Dashboard() {
  const { version, cameraStats, activity, setActivity } = useLive()
  const [summary, setSummary] = useState(null)
  const [charts, setCharts] = useState(null)
  const [error, setError] = useState(null)
  const [deleting, setDeleting] = useState(null)

  const deleteViolation = async (v) => {
    if (!window.confirm(`Delete violation ${v.code} (${v.violation_label}, worker ${v.worker_code})?\n\nThe record and its evidence photo will be permanently removed. This cannot be undone.`)) return
    setDeleting(v.id)
    try {
      await api.del(`/api/violations/${v.id}`)
      setSummary((prev) => prev && { ...prev, latest_violations: prev.latest_violations.filter((x) => x.id !== v.id) })
      load()
    } catch (e) {
      setError(e.message)
    } finally {
      setDeleting(null)
    }
  }

  const load = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.get('/api/dashboard/summary'), api.get('/api/dashboard/charts')])
      setSummary(s)
      setCharts(c)
      setError(null)
      setActivity((prev) => (prev.length ? prev : s.activity))
    } catch (e) {
      setError(e.message)
    }
  }, [setActivity])

  useEffect(() => { load() }, [load, version])
  useEffect(() => {
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  if (!summary) return <div className="loading">{error || 'Loading dashboard...'}</div>

  const cams = summary.cameras.map((c) => ({ ...c, runtime: { ...c.runtime, ...(cameraStats[c.id] || {}) } }))
  const online = cams.filter((c) => c.runtime.status === 'online')
  const liveCam = online[0]
  const inView = cams.reduce((a, c) => a + (c.runtime.status === 'online' ? c.runtime.persons || 0 : 0), 0)
  const ai = summary.ai

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Site Safety Dashboard</h1>
          <p className="muted">Real-time PPE compliance across all monitored areas</p>
        </div>
      </div>

      {summary && <ErrorNote error={error} />}

      {!ai.ready && (
        <div className={`alert ${ai.loading ? 'info' : 'error'}`}>
          <Cpu size={16} /> {ai.loading ? 'Loading AI models (PPE detection, person detection, Re-ID)...' : `AI engine not ready: ${ai.error}`}
        </div>
      )}

      <div className="kpis">
        <Kpi label="Total Cameras" value={summary.total_cameras} icon={Camera} tone="blue" />
        <Kpi label="Connected Cameras" value={online.length} icon={Wifi} tone="teal" sub={`${summary.total_cameras - online.length} offline / stopped`} />
        <Kpi label="Workers Detected Today" value={summary.workers_detected_today} icon={Users} tone="purple" sub={`${inView} in view now`} />
        <Kpi label="Today's PPE Violations" value={summary.violations_today} icon={AlertTriangle} tone="orange" />
        <Kpi label="Open Violations" value={summary.open_violations} icon={AlertOctagon} tone="red" sub={`${summary.under_review_violations} under review`} />
        <Kpi label="Closed Violations" value={summary.closed_violations} icon={CheckCircle2} tone="green" />
      </div>

      <div className="grid-2-1">
        <Card title={liveCam ? `Live: ${liveCam.name} · ${liveCam.location}` : 'Live Camera'} actions={<Link to="/live" className="link">Open live monitoring →</Link>}>
          {liveCam ? (
            <CameraStream cameraId={liveCam.id} running className="dash-stream" />
          ) : (
            <Empty>
              No camera is running. <Link className="link" to="/cameras">Add or start a camera</Link>
            </Empty>
          )}
        </Card>
        <Card title="Latest Violation Alerts" actions={<Link to="/violations" className="link">View all →</Link>}>
          {summary.latest_violations.length === 0 ? (
            <Empty>No violations recorded yet.</Empty>
          ) : (
            <ul className="alert-list">
              {summary.latest_violations.map((v) => (
                <li key={v.id}>
                  <Link to={`/violations?open=${v.id}`} className="alert-item">
                    {v.evidence_url ? <img src={v.evidence_url} alt="" /> : <div className="thumb-empty" />}
                    <div className="alert-text">
                      <div className="alert-row"><b>{v.violation_label}</b><StatusBadge status={v.status} /></div>
                      <div className="muted small">{v.code} · Worker {v.worker_code} · {pct(v.confidence)}</div>
                      <div className="muted small">{v.camera_name} · {v.location}</div>
                      <div className="muted small">{fmtDateTime(v.detected_at)}</div>
                    </div>
                  </Link>
                  <button
                    className="icon-btn danger alert-delete"
                    title={`Delete ${v.code}`}
                    disabled={deleting === v.id}
                    onClick={() => deleteViolation(v)}
                  >
                    <Trash2 size={16} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="grid-3">
        <Card title="Violations by Hour (Today)">
          <ResponsiveContainer width="100%" height={230}>
            <BarChart data={charts?.hourly_today || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="hour" tick={{ fontSize: 10 }} interval={2} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar isAnimationActive={false} dataKey="helmet" name="Missing Helmet" stackId="a" fill={HELMET} />
              <Bar isAnimationActive={false} dataKey="vest" name="Missing Vest" stackId="a" fill={VEST} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Violation Types (Last 7 Days)">
          {charts?.by_type_7d?.length ? (
            <ResponsiveContainer width="100%" height={230}>
              <PieChart>
                <Pie isAnimationActive={false} data={charts.by_type_7d} dataKey="count" nameKey="type" innerRadius={50} outerRadius={80} paddingAngle={3}>
                  {charts.by_type_7d.map((e, i) => <Cell key={e.key} fill={e.key === 'helmet' ? HELMET : e.key === 'vest' ? VEST : PIE_COLORS[i % 4]} />)}
                </Pie>
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : <Empty>No data yet</Empty>}
        </Card>
        <Card title="7-Day Violation Trend">
          <ResponsiveContainer width="100%" height={230}>
            <AreaChart data={charts?.daily_7d || []}>
              <CartesianGrid strokeDasharray="3 3" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
              <Tooltip />
              <Area isAnimationActive={false} type="monotone" dataKey="total" name="Violations" stroke="#2563eb" fill="#2563eb33" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Camera Status">
          {cams.length === 0 ? <Empty>No cameras configured.</Empty> : (
            <table className="table">
              <thead><tr><th>Camera</th><th>Location</th><th>Status</th><th>Workers</th><th>Compliant</th><th>Violations</th><th>AI FPS</th></tr></thead>
              <tbody>
                {cams.map((c) => (
                  <tr key={c.id}>
                    <td><b>{c.name}</b></td>
                    <td>{c.location}</td>
                    <td><CameraStatus status={c.runtime.status} /></td>
                    <td>{c.runtime.persons ?? 0}</td>
                    <td className="ok-text">{c.runtime.compliant ?? 0}</td>
                    <td className="bad-text">{c.runtime.violations ?? 0}</td>
                    <td>{c.runtime.ai_fps ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="muted small" style={{ marginTop: 10 }}>
            AI: {ai.ready ? `${ai.device} · ${ai.ppe_model} (${ai.supported_items.join(', ')})` : 'not ready'} · Re-ID: {ai.reid_ready ? 'active' : 'inactive'} · Duplicate alerts prevented: {summary.duplicates_suppressed}
          </div>
        </Card>
        <Card title={<span><Activity size={16} style={{ verticalAlign: -2 }} /> Real-Time Detection Activity</span>}>
          {activity.length === 0 ? <Empty>Waiting for activity...</Empty> : (
            <ul className="feed">
              {activity.slice(0, 40).map((a, i) => (
                <li key={`${a.time}-${i}`} className={`feed-${a.level}`}>
                  <span className="feed-time">{fmtTime(a.time)}</span>
                  <span>{a.message}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}
