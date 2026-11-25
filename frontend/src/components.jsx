import { useEffect, useState } from 'react'
import { X } from 'lucide-react'

export function StatusBadge({ status }) {
  const cls = { Open: 'red', 'Under Review': 'amber', Closed: 'green' }[status] || 'grey'
  return <span className={`badge ${cls}`}>{status}</span>
}

export function CameraStatus({ status }) {
  const map = {
    online: ['green', 'Online'],
    connecting: ['amber', 'Connecting'],
    reconnecting: ['amber', 'Reconnecting'],
    error: ['red', 'Error'],
    stopped: ['grey', 'Stopped'],
  }
  const [cls, label] = map[status] || ['grey', status || 'Unknown']
  return <span className={`badge ${cls}`}><span className="dot" />{label}</span>
}

export function Kpi({ label, value, icon: Icon, tone = 'blue', sub }) {
  return (
    <div className={`kpi ${tone}`}>
      <div className="kpi-icon">{Icon && <Icon size={20} />}</div>
      <div>
        <div className="kpi-value">{value ?? '-'}</div>
        <div className="kpi-label">{label}</div>
        {sub && <div className="kpi-sub">{sub}</div>}
      </div>
    </div>
  )
}

export function Card({ title, actions, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-head">
          <h3>{title}</h3>
          <div className="card-actions">{actions}</div>
        </div>
      )}
      <div className="card-body">{children}</div>
    </section>
  )
}

export function Modal({ title, onClose, children, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className={`modal ${wide ? 'wide' : ''}`} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

// Live MJPEG stream; reconnects when the camera restarts.
export function CameraStream({ cameraId, running, className = '' }) {
  const [key, setKey] = useState(0)
  useEffect(() => {
    if (running) setKey(Date.now())
  }, [running])
  if (!running) {
    return <div className={`stream placeholder ${className}`}><span>Camera stopped</span></div>
  }
  return (
    <img
      key={key}
      className={`stream ${className}`}
      src={`/api/cameras/${cameraId}/stream?k=${key}`}
      alt="Live camera"
      onError={() => setTimeout(() => setKey(Date.now()), 2000)}
    />
  )
}

export function ErrorNote({ error }) {
  if (!error) return null
  return <div className="alert error">{error}</div>
}

export function Empty({ children }) {
  return <div className="empty">{children}</div>
}
