import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BellOff, BellRing, ChevronLeft, ChevronRight, Search, Trash2 } from 'lucide-react'
import { api, fmtDateTime, pct } from '../api.js'
import { useLive } from '../live.jsx'
import { Card, Empty, ErrorNote, Modal, StatusBadge } from '../components.jsx'

const STATUSES = ['Open', 'Under Review', 'Closed']

function ViolationDetail({ id, onClose, onSaved }) {
  const [v, setV] = useState(null)
  const [form, setForm] = useState({ status: 'Open', corrective_action: '', supervisor_notes: '' })
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [ok, setOk] = useState(false)

  useEffect(() => {
    api.get(`/api/violations/${id}`).then((d) => {
      setV(d)
      setForm({ status: d.status, corrective_action: d.corrective_action, supervisor_notes: d.supervisor_notes })
    }).catch((e) => setError(e.message))
  }, [id])

  const remove = async () => {
    if (!window.confirm(`Delete violation ${v.code} (${v.violation_label}, worker ${v.worker_code})?\n\nThe record and its evidence photo will be permanently removed. This cannot be undone.`)) return
    setSaving(true)
    setError(null)
    try {
      await api.del(`/api/violations/${id}`)
      onSaved()
      onClose()
    } catch (e) {
      setError(e.message)
      setSaving(false)
    }
  }

  const save = async (override) => {
    setSaving(true)
    setError(null)
    setOk(false)
    try {
      const body = { ...form, ...override }
      const d = await api.patch(`/api/violations/${id}`, body)
      setV(d)
      setForm({ status: d.status, corrective_action: d.corrective_action, supervisor_notes: d.supervisor_notes })
      setOk(true)
      onSaved()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal title={v ? `${v.code} · ${v.violation_label}` : 'Violation'} onClose={onClose} wide>
      <ErrorNote error={error} />
      {!v ? <div className="loading">Loading...</div> : (
        <div className="detail">
          <div className="detail-img">
            {v.evidence_url ? <a href={v.evidence_url} target="_blank" rel="noreferrer"><img src={v.evidence_url} alt="Evidence" /></a> : <Empty>No evidence image</Empty>}
          </div>
          <div className="detail-side">
            <dl className="facts">
              <dt>Violation ID</dt><dd>{v.code}</dd>
              <dt>Worker ID</dt><dd>{v.worker_code}</dd>
              <dt>Violation Type</dt><dd className="bad-text"><b>{v.violation_label}</b></dd>
              <dt>Camera</dt><dd>{v.camera_name}</dd>
              <dt>Project Location</dt><dd>{v.location || '-'}</dd>
              <dt>Date & Time</dt><dd>{fmtDateTime(v.detected_at)}</dd>
              <dt>Last Seen</dt><dd>{fmtDateTime(v.last_seen_at)}</dd>
              <dt>Detection Confidence</dt><dd>{pct(v.confidence)}</dd>
              <dt>Sightings</dt><dd>{v.occurrences} ({(v.cameras_involved || []).join(', ')})</dd>
              <dt>Notification</dt><dd>{v.notified ? 'Sent' : v.notification_error ? <span className="bad-text">{v.notification_error}</span> : 'Not sent'}</dd>
              <dt>Status</dt><dd><StatusBadge status={v.status} /></dd>
            </dl>
            <div className="form">
              <label>Status
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s}>{s}</option>)}
                </select>
              </label>
              <label>Corrective Action
                <textarea rows={3} value={form.corrective_action} onChange={(e) => setForm({ ...form, corrective_action: e.target.value })} placeholder="e.g. Worker instructed and provided with a safety helmet; toolbox talk delivered." />
              </label>
              <label>Supervisor Notes
                <textarea rows={3} value={form.supervisor_notes} onChange={(e) => setForm({ ...form, supervisor_notes: e.target.value })} />
              </label>
              {ok && <div className="alert success">Saved.</div>}
              <div className="modal-actions">
                <button className="btn danger" style={{ marginRight: 'auto' }} onClick={remove} disabled={saving}><Trash2 size={15} /> Delete</button>
                <button className="btn" onClick={() => save()} disabled={saving}>Save</button>
                {v.status !== 'Closed' && (
                  <button className="btn success" disabled={saving} onClick={() => save({ status: 'Closed' })}>Close Violation</button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )
}

export default function Violations() {
  const { version } = useLive()
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState({ status: '', violation_type: '', camera_id: '', date_from: '', date_to: '', search: '' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState({ items: [], total: 0, page_size: 25 })
  const [cams, setCams] = useState([])
  const [error, setError] = useState(null)
  const openId = params.get('open')

  const load = useCallback(async () => {
    const q = new URLSearchParams({ page, page_size: 25 })
    Object.entries(filters).forEach(([k, v]) => v && q.set(k, v))
    try {
      setData(await api.get(`/api/violations?${q}`))
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [filters, page])

  useEffect(() => { load() }, [load, version])
  useEffect(() => { api.get('/api/cameras').then(setCams).catch(() => {}) }, [])

  const setF = (k) => (e) => { setPage(1); setFilters({ ...filters, [k]: e.target.value }) }
  const pages = Math.max(1, Math.ceil(data.total / data.page_size))

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Violation Management</h1>
          <p className="muted">Review PPE violations, record corrective actions and close them once resolved.</p>
        </div>
      </div>
      <ErrorNote error={error} />
      <Card>
        <div className="filters">
          <div className="search"><Search size={16} /><input placeholder="Search ID, worker, camera, location..." value={filters.search} onChange={setF('search')} /></div>
          <select value={filters.status} onChange={setF('status')}><option value="">All statuses</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={filters.violation_type} onChange={setF('violation_type')}><option value="">All types</option><option value="helmet">Missing Safety Helmet</option><option value="vest">Missing Safety Vest</option></select>
          <select value={filters.camera_id} onChange={setF('camera_id')}><option value="">All cameras</option>{cams.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <label className="inline">From <input type="date" value={filters.date_from} onChange={setF('date_from')} /></label>
          <label className="inline">To <input type="date" value={filters.date_to} onChange={setF('date_to')} /></label>
        </div>
        {data.items.length === 0 ? <Empty>No violations match the current filters.</Empty> : (
          <table className="table hover">
            <thead>
              <tr><th>Evidence</th><th>Violation ID</th><th>Worker ID</th><th>Violation Type</th><th>Camera</th><th>Project Location</th><th>Date & Time</th><th>Confidence</th><th>Status</th><th>Alert</th></tr>
            </thead>
            <tbody>
              {data.items.map((v) => (
                <tr key={v.id} onClick={() => setParams({ open: v.id })}>
                  <td>{v.evidence_url ? <img className="thumb" src={v.evidence_url} alt="" loading="lazy" /> : <div className="thumb-empty" />}</td>
                  <td className="mono"><b>{v.code}</b></td>
                  <td>{v.worker_code}</td>
                  <td className="bad-text">{v.violation_label}</td>
                  <td>{v.camera_name}{v.occurrences > 1 && <div className="muted small">{v.occurrences} sightings</div>}</td>
                  <td>{v.location}</td>
                  <td>{fmtDateTime(v.detected_at)}</td>
                  <td>{pct(v.confidence)}</td>
                  <td><StatusBadge status={v.status} /></td>
                  <td title={v.notification_error || (v.notified ? 'Notification sent' : 'Not sent')}>
                    {v.notified ? <BellRing size={16} className="ok-text" /> : <BellOff size={16} className="muted" />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="pager">
          <span className="muted">{data.total} violation(s)</span>
          <button className="icon-btn" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={16} /></button>
          <span>Page {page} / {pages}</span>
          <button className="icon-btn" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={16} /></button>
        </div>
      </Card>
      {openId && <ViolationDetail id={openId} onClose={() => setParams({})} onSaved={load} />}
    </div>
  )
}
