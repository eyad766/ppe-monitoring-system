// WebSocket connection to the backend: live camera stats, violations and activity feed.
import { createContext, useContext, useEffect, useRef, useState } from 'react'

const LiveContext = createContext(null)

export function LiveProvider({ children }) {
  const [connected, setConnected] = useState(false)
  const [cameraStats, setCameraStats] = useState({})
  const [activity, setActivity] = useState([])
  const [toasts, setToasts] = useState([])
  const [version, setVersion] = useState(0) // bumps when data changes -> pages refetch
  const listeners = useRef(new Set())

  useEffect(() => {
    let ws
    let retry
    let closed = false
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/ws`)
      ws.onopen = () => setConnected(true)
      ws.onclose = () => {
        setConnected(false)
        if (!closed) retry = setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
      ws.onmessage = (ev) => {
        let msg
        try {
          msg = JSON.parse(ev.data)
        } catch {
          return
        }
        const { type, data } = msg
        if (type === 'camera_stats' || type === 'camera_status') {
          setCameraStats((prev) => ({ ...prev, [data.camera_id]: data }))
        } else if (type === 'activity') {
          setActivity((prev) => [data, ...prev].slice(0, 100))
        } else if (type === 'violation_created') {
          setToasts((prev) => [...prev, { id: `${data.id}-${Date.now()}`, v: data }].slice(-4))
          beep()
        }
        if (['violation_created', 'violation_updated', 'violation_deleted', 'camera_added', 'camera_removed', 'camera_status', 'settings_updated'].includes(type)) {
          setVersion((v) => v + 1)
        }
        listeners.current.forEach((fn) => fn(msg))
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [])

  const dismissToast = (id) => setToasts((prev) => prev.filter((t) => t.id !== id))
  const subscribe = (fn) => {
    listeners.current.add(fn)
    return () => listeners.current.delete(fn)
  }

  return (
    <LiveContext.Provider value={{ connected, cameraStats, activity, setActivity, toasts, dismissToast, version, subscribe }}>
      {children}
    </LiveContext.Provider>
  )
}

export const useLive = () => useContext(LiveContext)

let audioCtx
function beep() {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)()
    const o = audioCtx.createOscillator()
    const g = audioCtx.createGain()
    o.type = 'square'
    o.frequency.value = 880
    g.gain.value = 0.04
    o.connect(g)
    g.connect(audioCtx.destination)
    o.start()
    o.stop(audioCtx.currentTime + 0.25)
  } catch {
    /* audio not allowed until the user interacts with the page */
  }
}
