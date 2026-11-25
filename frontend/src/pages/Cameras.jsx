import { useCallback, useEffect, useState } from 'react'
import { Pencil, Play, Plus, RefreshCw, Square, Trash2, Webcam } from 'lucide-react'
import { api } from '../api.js'
import { useLive } from '../live.jsx'
import { Card, CameraStatus, Empty, ErrorNote, Modal } from '../components.jsx'

const EMPTY = { name: '', location: '', tower: '', floor: '', source_type: 'webcam', source: '0', enabled: true, auto_start: false }
const TYPE_LABEL = { webcam: 'Local webcam', rtsp: 'RTSP stream', http: 'HTTP / MJPEG', file: 'Video file' }

function CameraForm({ initial, onSaved, onClose }) {
  const [f, setF] = useState(initial || EMPTY)
  const [devices, setDevices] = useState(null)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  const scan = async () => {
    setScanning(true)
    setError(null)
    try {
      const d = await api.get('/api/devices/webcams')
      setDevices(d)
      const iriun = d.find((x) => x.is_iriun && x.available !== false)
      const first = iriun || d.find((x) => x.available)
      if (first && f.source_type === 'webcam' && !initial) setF((p) => ({ ...p, source: String(first.index) }))
    } catch (e) {
      setError(e.message)
    } finally {
      setScanning(false)
    }
  }
  useEffect(() => {
    if (f.source_type === 'webcam' && devices === null) scan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f.source_type])

  const save = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      const body = { ...f, source: String(f.source).trim() }
      const out = initial?.id ? await api.put(`/api/cameras/${initial.id}`, body) : await api.post('/api/cameras', body)
      onSaved(out)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={save} className="form">
      <ErrorNote error={error} />
      <div className="form-grid">
        <label>Camera name *<input required value={f.name} onChange={set('name')} placeholder="Camera 01" /></label>
        <label>Project location *<input required value={f.location} onChange={set('location')} placeholder="Tower B - Level 8" /></label>
        <label>Tower / Zone<input value={f.tower} onChange={set('tower')} placeholder="Tower B" /></label>
        <label>Floor / Level<input value={f.floor} onChange={set('floor')} placeholder="Level 8" /></label>
        <label>Source type
          <select value={f.source_type} onChange={(e) => setF({ ...f, source_type: e.target.value, source: e.target.value === 'webcam' ? '0' : '' })}>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
        {f.source_type === 'webcam' ? (
          <label>Webcam device
            <div className="row gap">
              <select value={f.source} onChange={set('source')} style={{ flex: 1 }}>
                {(devices || [{ index: Number(f.source), name: `Device ${f.source}` }]).map((d) => (
                  <option key={d.index} value={String(d.index)}>
                    [{d.index}] {d.name}{d.resolution ? ` - ${d.resolution}` : ''}{d.in_use ? ' (in use)' : d.available === false ? ' (no signal)' : ''}
                  </option>
                ))}
              </select>
              <button type="button" className="btn sm" onClick={scan} disabled={scanning}><RefreshCw size={14} className={scanning ? 'spin' : ''} /> Detect</button>
            </div>
          </label>
        ) : (
          <label>{f.source_type === 'file' ? 'Video file path' : 'Stream URL'}
            <input required value={f.source} onChange={set('source')}
              placeholder={f.source_type === 'rtsp' ? 'rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101' : f.source_type === 'http' ? 'http://192.168.1.50:8080/video' : 'C:\\Videos\\site.mp4'} />
          </label>
        )}
      </div>
      {f.source_type === 'webcam' && devices && (
        <div className="muted small">
          {devices.length === 0 ? 'No webcams found. Make sure Iriun Webcam is running on both the PC and the phone.' :
            `${devices.length} device(s) found. ${devices.some((d) => d.is_iriun) ? 'Iriun Webcam detected.' : 'Iriun Webcam not listed - start the Iriun app on PC and phone, then press Detect.'}`}
        </div>
      )}
      <div className="row gap">
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={set('enabled')} /> Enabled</label>
        <label className="check"><input type="checkbox" checked={f.auto_start} onChange={set('auto_start')} /> Start automatically when the system starts</label>
      </div>
      <div className="modal-actions">
        <button type="button" className="btn" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={saving}>{saving ? 'Saving...' : 'Save Camera'}</button>
      </div>
    </form>
  )
}

export default function Cameras() {
  const { version, cameraStats } = useLive()
  const [cams, setCams] = useState([])
  const [editing, setEditing] = useState(null) // null | {} (new) | camera
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState({})

  const load = useCallback(() => api.get('/api/cameras').then(setCams).catch((e) => setError(e.message)), [])
  useEffect(() => { load() }, [load, version])

  const act = async (id, fn) => {
    setBusy((b) => ({ ...b, [id]: true }))
    setError(null)
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy((b) => ({ ...b, [id]: false }))
    }
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Camera Management</h1>
          <p className="muted">Connect CCTV / IP cameras (RTSP, HTTP) or local webcams such as Iriun Webcam and assign each one to a project location.</p>
        </div>
        <button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> Add Camera</button>
      </div>
      <ErrorNote error={error} />
      <Card>
        {cams.length === 0 ? (
          <Empty>
            <Webcam size={32} />
            <div>No cameras configured yet.</div>
            <button className="btn primary" onClick={() => setEditing({})}><Plus size={16} /> Add your first camera</button>
          </Empty>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Camera</th><th>Location</th><th>Tower</th><th>Floor</th><th>Source</th><th>Status</th><th>Auto start</th><th style={{ textAlign: 'right' }}>Actions</th></tr>
            </thead>
            <tbody>
              {cams.map((c) => {
                const r = { ...c.runtime, ...(cameraStats[c.id] || {}) }
                const running = r.status !== 'stopped'
                return (
                  <tr key={c.id} className={!c.enabled ? 'disabled' : ''}>
                    <td><b>{c.name}</b>{!c.enabled && <span className="muted small"> (disabled)</span>}</td>
                    <td>{c.location}</td>
                    <td>{c.tower || '-'}</td>
                    <td>{c.floor || '-'}</td>
                    <td><span className="muted small">{TYPE_LABEL[c.source_type]}</span><div className="mono small ellipsis" title={c.source}>{c.source_type === 'webcam' ? `Device ${c.source}` : c.source}</div></td>
                    <td><CameraStatus status={r.status} />{r.error && r.status !== 'online' && <div className="bad-text small ellipsis" title={r.error}>{r.error}</div>}</td>
                    <td>{c.auto_start ? 'Yes' : 'No'}</td>
                    <td>
                      <div className="row gap end">
                        {running ? (
                          <button className="btn sm danger" disabled={busy[c.id]} onClick={() => act(c.id, () => api.post(`/api/cameras/${c.id}/stop`))}><Square size={14} /> Stop</button>
                        ) : (
                          <button className="btn sm primary" disabled={busy[c.id] || !c.enabled} onClick={() => act(c.id, () => api.post(`/api/cameras/${c.id}/start`))}><Play size={14} /> Start</button>
                        )}
                        <button className="icon-btn" title="Edit" onClick={() => setEditing(c)}><Pencil size={16} /></button>
                        <button className="icon-btn danger" title="Remove" onClick={() => {
                          if (window.confirm(`Remove ${c.name}? Recorded violations are kept.`)) act(c.id, () => api.del(`/api/cameras/${c.id}`))
                        }}><Trash2 size={16} /></button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Card>
      {editing && (
        <Modal title={editing.id ? `Edit ${editing.name}` : 'Add Camera'} onClose={() => setEditing(null)}>
          <CameraForm initial={editing.id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
        </Modal>
      )}
    </div>
  )
}
