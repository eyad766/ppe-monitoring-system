import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Maximize2, Minimize2, Play, Square } from 'lucide-react'
import { api } from '../api.js'
import { useLive } from '../live.jsx'
import { CameraStatus, CameraStream, Empty, ErrorNote } from '../components.jsx'

export default function LiveMonitoring() {
  const { version, cameraStats } = useLive()
  const [cams, setCams] = useState([])
  const [focus, setFocus] = useState(null)
  const [busy, setBusy] = useState({})
  const [error, setError] = useState(null)

  const load = useCallback(() => api.get('/api/cameras').then(setCams).catch((e) => setError(e.message)), [])
  useEffect(() => { load() }, [load, version])

  const act = async (id, action) => {
    setBusy((b) => ({ ...b, [id]: true }))
    setError(null)
    try {
      await api.post(`/api/cameras/${id}/${action}`)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy((b) => ({ ...b, [id]: false }))
    }
  }

  const list = cams.map((c) => ({ ...c, runtime: { ...c.runtime, ...(cameraStats[c.id] || {}) } }))
  const shown = focus ? list.filter((c) => c.id === focus) : list

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Live Monitoring</h1>
          <p className="muted">
            <span className="legend green" /> PPE compliant <span className="legend red" /> PPE violation
            <span className="legend amber" /> PPE unknown (not enough evidence - no violation is raised)
          </p>
        </div>
      </div>
      <ErrorNote error={error} />
      {list.length === 0 && <Empty>No cameras yet. <Link className="link" to="/cameras">Add a camera</Link></Empty>}
      <div className={focus ? 'live-grid single' : 'live-grid'}>
        {shown.map((c) => {
          const r = c.runtime
          const running = r.status !== 'stopped'
          return (
            <div key={c.id} className="live-tile">
              <div className="live-head">
                <div>
                  <b>{c.name}</b> <span className="muted">· {c.location}</span>
                </div>
                <div className="row gap">
                  <CameraStatus status={r.status} />
                  {running ? (
                    <button className="btn sm danger" disabled={busy[c.id]} onClick={() => act(c.id, 'stop')}><Square size={14} /> Stop</button>
                  ) : (
                    <button className="btn sm primary" disabled={busy[c.id] || !c.enabled} onClick={() => act(c.id, 'start')}><Play size={14} /> Start</button>
                  )}
                  <button className="icon-btn" title={focus ? 'Show all' : 'Enlarge'} onClick={() => setFocus(focus ? null : c.id)}>
                    {focus ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                  </button>
                </div>
              </div>
              <CameraStream cameraId={c.id} running={running} />
              {r.error && r.status !== 'online' && <div className="alert error small">{r.error}</div>}
              <div className="live-stats">
                <div><span>Workers</span><b>{r.persons ?? 0}</b></div>
                <div className="ok-text"><span>Compliant</span><b>{r.compliant ?? 0}</b></div>
                <div className="bad-text"><span>Violations</span><b>{r.violations ?? 0}</b></div>
                <div className="warn-text"><span>Unknown</span><b>{r.unknown ?? 0}</b></div>
                <div><span>AI FPS</span><b>{r.ai_fps ?? 0}</b></div>
                <div><span>Inference</span><b>{Math.round(r.infer_ms || 0)} ms</b></div>
                <div><span>Video</span><b>{r.resolution || '-'}</b></div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
