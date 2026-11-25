import { useEffect, useState } from 'react'
import { Save, Send } from 'lucide-react'
import { api } from '../api.js'
import { Card, ErrorNote } from '../components.jsx'

function Num({ label, k, f, setF, step = 1, min, max, hint }) {
  return (
    <label>{label}
      <input type="number" step={step} min={min} max={max} value={f[k] ?? ''} onChange={(e) => setF({ ...f, [k]: e.target.value === '' ? '' : Number(e.target.value) })} />
      {hint && <span className="hint">{hint}</span>}
    </label>
  )
}

export default function Settings() {
  const [f, setF] = useState(null)
  const [info, setInfo] = useState(null)
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  useEffect(() => {
    api.get('/api/settings').then(setF).catch((e) => setError(e.message))
    api.get('/api/system/info').then(setInfo).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    setError(null)
    setMsg(null)
    try {
      const body = { ...f }
      delete body.telegram_bot_token_set
      setF(await api.put('/api/settings', body))
      setMsg('Settings saved and applied.')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const testTelegram = async () => {
    setTesting(true)
    setError(null)
    setMsg(null)
    try {
      const r = await api.post('/api/settings/telegram/test', { telegram_bot_token: f.telegram_bot_token, telegram_chat_id: f.telegram_chat_id })
      setMsg(`Test message sent by @${r.bot}. Check your Telegram chat.`)
    } catch (e) {
      setError(e.message)
    } finally {
      setTesting(false)
    }
  }

  if (!f) return <div className="loading">{error || 'Loading settings...'}</div>
  const toggleItem = (item) => {
    const cur = new Set(f.required_ppe)
    cur.has(item) ? cur.delete(item) : cur.add(item)
    setF({ ...f, required_ppe: [...cur] })
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="muted">Detection sensitivity, duplicate prevention, worker re-identification and notifications.</p>
        </div>
        <button className="btn primary" onClick={save} disabled={saving}><Save size={16} /> {saving ? 'Saving...' : 'Save Settings'}</button>
      </div>
      <ErrorNote error={error} />
      {msg && <div className="alert success">{msg}</div>}

      <div className="grid-2">
        <Card title="PPE Detection">
          <div className="form">
            <div>
              <div className="label">Required PPE</div>
              <div className="row gap">
                {[['helmet', 'Safety Helmet'], ['vest', 'Safety Vest']].map(([k, l]) => (
                  <label key={k} className="check"><input type="checkbox" checked={f.required_ppe.includes(k)} onChange={() => toggleItem(k)} /> {l}</label>
                ))}
                <label className="check disabled" title="The current AI model has no safety-shoe classes"><input type="checkbox" disabled /> Safety Shoes (needs a model with shoe classes)</label>
              </div>
            </div>
            <div className="form-grid">
              <label>Person detector
                <select value={f.person_detector} onChange={(e) => setF({ ...f, person_detector: e.target.value })}>
                  <option value="coco">Dedicated person model (recommended)</option>
                  <option value="ppe">PPE model "Person" class (faster)</option>
                </select>
              </label>
              <Num label="Person confidence" k="person_confidence" f={f} setF={setF} step={0.05} min={0.05} max={0.99} />
              <Num label="PPE present confidence" k="ppe_present_confidence" f={f} setF={setF} step={0.05} min={0.05} max={0.99} hint="Hardhat / Safety Vest" />
              <Num label="PPE missing confidence" k="ppe_missing_confidence" f={f} setF={setF} step={0.05} min={0.05} max={0.99} hint="NO-Hardhat / NO-Safety Vest" />
              <Num label="AI input size (px)" k="inference_size" f={f} setF={setF} step={32} min={320} max={1280} />
              <Num label="Max AI frames / second" k="max_detection_fps" f={f} setF={setF} min={1} max={30} />
              <Num label="Decision window (AI frames)" k="state_window" f={f} setF={setF} min={1} max={60} />
              <Num label="Agreement ratio" k="state_min_ratio" f={f} setF={setF} step={0.05} min={0.3} max={1} />
              <Num label="Violation must persist (s)" k="violation_min_seconds" f={f} setF={setF} step={0.5} min={0} max={60} />
            </div>
            <p className="muted small">A violation is only raised when the model positively detects a missing item (NO-Hardhat / NO-Safety Vest) consistently. When the evidence is insufficient the worker is shown as PPE UNKNOWN and nothing is recorded.</p>
          </div>
        </Card>

        <Card title="Duplicate Prevention & Worker Re-Identification">
          <div className="form">
            <div className="form-grid">
              <Num label="Same-incident window (s)" k="duplicate_window_seconds" f={f} setF={setF} min={0} max={86400} hint="Same worker + same violation within this time = one incident" />
              <Num label="Notification cooldown (s)" k="notification_cooldown_seconds" f={f} setF={setF} min={0} max={86400} hint="Per worker and violation type" />
            </div>
            <label className="check"><input type="checkbox" checked={f.reid_enabled} onChange={(e) => setF({ ...f, reid_enabled: e.target.checked })} /> Enable cross-camera Re-ID (recognise the same worker on other cameras)</label>
            <div className="form-grid">
              <Num label="Match similarity threshold" k="reid_similarity_threshold" f={f} setF={setF} step={0.01} min={0.3} max={0.99} hint="Higher = fewer merges" />
              <Num label="Required margin over 2nd best" k="reid_margin" f={f} setF={setF} step={0.01} min={0} max={0.5} />
              <Num label="Identity check threshold" k="reid_drift_threshold" f={f} setF={setF} step={0.01} min={0} max={0.9} />
              <Num label="Remember workers for (min)" k="reid_memory_minutes" f={f} setF={setF} min={1} max={1440} />
              <Num label="Min. person height for Re-ID (px)" k="reid_min_crop_height" f={f} setF={setF} min={32} max={1000} />
            </div>
            <p className="muted small">When identification confidence is low, the system creates a new Worker ID instead of merging two different workers.</p>
          </div>
        </Card>

        <Card title="Telegram Notifications">
          <div className="form">
            <label className="check"><input type="checkbox" checked={f.telegram_enabled} onChange={(e) => setF({ ...f, telegram_enabled: e.target.checked })} /> Send violation alerts to Telegram</label>
            <label>Bot Token
              <input type="password" autoComplete="off" value={f.telegram_bot_token} onChange={(e) => setF({ ...f, telegram_bot_token: e.target.value })} placeholder="123456789:AA..." />
              <span className="hint">{f.telegram_bot_token_set ? 'A token is stored (shown masked). Type a new one to replace it.' : 'Create a bot with @BotFather and paste its token.'}</span>
            </label>
            <label>Chat ID
              <input value={f.telegram_chat_id} onChange={(e) => setF({ ...f, telegram_chat_id: e.target.value })} placeholder="e.g. 123456789 or -100123... for a group" />
            </label>
            <label className="check"><input type="checkbox" checked={f.telegram_send_photo} onChange={(e) => setF({ ...f, telegram_send_photo: e.target.checked })} /> Attach the evidence photo</label>
            <div className="row gap">
              <button className="btn" onClick={testTelegram} disabled={testing}><Send size={16} /> {testing ? 'Sending...' : 'Send Test Message'}</button>
              <span className="muted small">Remember to press Save Settings.</span>
            </div>
          </div>
        </Card>

        <Card title="System Information">
          {info ? (
            <dl className="facts">
              <dt>Application</dt><dd>{info.app} {info.version}</dd>
              <dt>AI engine</dt><dd>{info.ai.ready ? `Ready on ${info.ai.device}` : info.ai.loading ? 'Loading...' : `Error: ${info.ai.error}`}</dd>
              <dt>PPE model</dt><dd>{info.ai.ppe_model}</dd>
              <dt>Model classes</dt><dd className="small">{info.ai.ppe_classes.join(', ')}</dd>
              <dt>Person model</dt><dd>{info.ai.person_model || 'PPE model Person class'}</dd>
              <dt>Re-ID model</dt><dd>{info.reid.model} ({info.reid.ready ? 'ready' : info.reid.error || 'not loaded'})</dd>
              <dt>Tracker</dt><dd>ByteTrack + appearance verification</dd>
              <dt>Python / OpenCV</dt><dd>{info.python} / {info.opencv}</dd>
              <dt>PyTorch</dt><dd>{info.torch} {info.cuda_available ? '(CUDA GPU available)' : '(CPU)'}</dd>
              <dt>Operating system</dt><dd>{info.os}</dd>
            </dl>
          ) : 'Loading...'}
        </Card>
      </div>
    </div>
  )
}
