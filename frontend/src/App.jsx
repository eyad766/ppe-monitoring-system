import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { AlertTriangle, Camera, LayoutDashboard, MonitorPlay, Settings as SettingsIcon, ShieldCheck, X } from 'lucide-react'
import { useLive } from './live.jsx'
import { fmtTime } from './api.js'
import Dashboard from './pages/Dashboard.jsx'
import LiveMonitoring from './pages/LiveMonitoring.jsx'
import Cameras from './pages/Cameras.jsx'
import Violations from './pages/Violations.jsx'
import Settings from './pages/Settings.jsx'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/live', label: 'Live Monitoring', icon: MonitorPlay },
  { to: '/violations', label: 'Violations', icon: AlertTriangle },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/settings', label: 'Settings', icon: SettingsIcon },
]

function Clock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return (
    <div className="clock">
      <span>{now.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })}</span>
      <strong>{now.toLocaleTimeString('en-US')}</strong>
    </div>
  )
}

function Toasts() {
  const { toasts, dismissToast } = useLive()
  const nav = useNavigate()
  useEffect(() => {
    if (!toasts.length) return
    const t = setTimeout(() => dismissToast(toasts[0].id), 12000)
    return () => clearTimeout(t)
  }, [toasts, dismissToast])
  return (
    <div className="toasts">
      {toasts.map(({ id, v }) => (
        <div key={id} className="toast" onClick={() => { nav(`/violations?open=${v.id}`); dismissToast(id) }}>
          {v.evidence_url && <img src={v.evidence_url} alt="evidence" />}
          <div className="toast-body">
            <div className="toast-title"><AlertTriangle size={16} /> PPE VIOLATION DETECTED</div>
            <div><b>{v.violation_label}</b></div>
            <div>Worker {v.worker_code} · {v.camera_name}</div>
            <div className="muted">{v.location} · {fmtTime(v.detected_at)}</div>
          </div>
          <button className="icon-btn" onClick={(e) => { e.stopPropagation(); dismissToast(id) }}><X size={16} /></button>
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { connected } = useLive()
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-logo"><ShieldCheck size={22} /></div>
          <div>
            <div className="brand-name">SiteGuard AI</div>
            <div className="brand-sub">PPE Monitoring System</div>
          </div>
        </div>
        <nav>
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              <Icon size={18} /> <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className={`conn ${connected ? 'ok' : 'bad'}`}><span className="dot" />{connected ? 'Real-time link active' : 'Reconnecting...'}</div>
          <div className="muted small">Phase 1 · HSE Department</div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="topbar-title">AI-Powered PPE Compliance Monitoring</div>
          <Clock />
        </header>
        <div className="content">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<LiveMonitoring />} />
            <Route path="/violations" element={<Violations />} />
            <Route path="/cameras" element={<Cameras />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Dashboard />} />
          </Routes>
        </div>
      </main>
      <Toasts />
    </div>
  )
}
