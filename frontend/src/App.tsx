import { useEffect, useRef, useState } from 'react'
import './App.css'

type Platform = 'linkedin' | 'x' | 'instagram' | 'youtube' | 'facebook'
type Draft = { platform: string; processed_content: string }
type ApiResponse = { processed_content?: Draft[]; message?: string }

const platforms: { id: Platform; name: string; mark: string; note: string }[] = [
  { id: 'linkedin', name: 'LinkedIn', mark: 'in', note: 'Professional & insightful' },
  { id: 'x', name: 'X', mark: '𝕏', note: 'Sharp & conversational' },
  { id: 'instagram', name: 'Instagram', mark: '', note: 'Visual-first & engaging' },
  { id: 'youtube', name: 'YouTube', mark: '▶', note: 'Video script & story' },
  { id: 'facebook', name: 'Facebook', mark: 'f', note: 'Conversational & community' },
]

const quotes = [
  'Finding the story worth sharing…',
  'Shaping your idea for every platform…',
  'Giving each draft its own voice…',
  'Polishing the details that make it yours…',
  'Making sure every word earns its place…',
]

function PlatformIcon({ platform }: { platform: Platform }) {
  if (platform === 'instagram') {
    return <svg className="instagram-icon" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3.25" y="3.25" width="17.5" height="17.5" rx="5" />
      <circle cx="12" cy="12" r="4.1" />
      <circle className="instagram-flash" cx="17.7" cy="6.6" r="1" />
    </svg>
  }
  return <>{platforms.find((item) => item.id === platform)?.mark}</>
}

function FormattedDraft({ text }: { text: string }) {
  return <div className="draft-copy">{text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => {
    const bold = part.startsWith('**') && part.endsWith('**')
    return <span key={index}>{bold ? <strong>{part.slice(2, -2)}</strong> : part}</span>
  })}</div>
}
function App() {
  const [content, setContent] = useState('')
  const [audience, setAudience] = useState('General audience')
  const [selected, setSelected] = useState<Platform[]>(['linkedin', 'instagram'])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [quoteIndex, setQuoteIndex] = useState(0)
  const [copied, setCopied] = useState('')
  const requestController = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!loading) return
    const timer = window.setInterval(() => setQuoteIndex((index) => (index + 1) % quotes.length), 5200)
    return () => window.clearInterval(timer)
  }, [loading])

  const togglePlatform = (platform: Platform) => {
    setSelected((current) => current.includes(platform)
      ? current.filter((item) => item !== platform)
      : [...current, platform])
  }

  async function generate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!content.trim()) { setError('Add an idea or source text to get started.'); return }
    if (!selected.length) { setError('Choose at least one platform for your drafts.'); return }
    setLoading(true)
    setError('')
    setDrafts([])
    setMessage('')
    setQuoteIndex(0)
    const controller = new AbortController()
    requestController.current = controller
    try {
      const response = await fetch('/api/content/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: content.trim(), audience: audience.trim() || 'general', platforms: selected }),
        signal: controller.signal,
      })
      const data = await response.json().catch(() => ({})) as ApiResponse
      if (!response.ok) {
        const message = response.status === 422
          ? 'Please check your request and try again.'
          : response.status === 504
            ? 'We couldn’t finish creating your content in time. Please try again.'
            : response.status === 503
              ? 'We’re having trouble right now. Please try again shortly.'
              : 'We couldn’t create your content right now. Please try again shortly.'
        throw new Error(message)
      }
      setDrafts(data.processed_content ?? [])
      setMessage(data.message ?? '')
      if (!data.message && !data.processed_content?.length) setError('We couldn’t create your content right now. Please try again.')
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') return
      setError(reason instanceof Error && (reason.message.startsWith('We ') || reason.message.startsWith('Please '))
        ? reason.message
        : 'We couldn’t reach the content studio. Check your connection and try again.')
    } finally {
      if (requestController.current === controller) {
        requestController.current = null
        setLoading(false)
      }
    }
  }

  function cancelGeneration() {
    requestController.current?.abort()
    requestController.current = null
    setLoading(false)
    setError('Generation cancelled. Your idea is still here whenever you are ready.')
  }

  async function copyDraft(draft: Draft) {
    try {
      await navigator.clipboard.writeText(draft.processed_content)
      setCopied(draft.platform)
      window.setTimeout(() => setCopied(''), 1800)
    } catch { setError('Clipboard access is unavailable in this browser.') }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Storyloom home"><span className="brand-mark">s</span><span>storyloom<span className="brand-period">.</span></span></a>
        <div className="topbar-right"><span className="topbar-caption">ONE IDEA, POSTS FOR EVERY PLATFORM</span><span className="status-dot" /> <span className="status-label">Ready to create</span></div>
      </header>

      <main id="top">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> YOUR AI CONTENT TEAM</div>
            <h1>One idea.<br /><em>Ready-to-post</em> content.</h1>
            <p className="hero-intro">Share an idea or source, choose your platforms, and our AI agents will work together to create tailored, ready-to-post drafts for your audience.</p>
            <div className="hero-footnote"><span className="sparkle">✳</span> Review, refine, and post when you’re ready.</div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <div className="art-sun" /><div className="art-leaf leaf-one" /><div className="art-leaf leaf-two" />
            <div className="art-card card-back"><span>your idea</span><b>✳</b></div>
            <div className="art-card card-front"><span>made to travel</span><div className="mini-lines"><i /><i /><i /></div><b>↗</b></div>
            <span className="art-caption">A little spark<br />goes a long way.</span>
          </div>
        </section>

        <section className="workspace" aria-label="Content creation workspace">
          <form className="brief-panel" onSubmit={generate}>
            <div className="section-kicker"><span>01</span> YOUR IDEA OR SOURCE</div>
            <label className="field-label" htmlFor="idea">What would you like to share?</label>
            <p className="field-hint">Give the agents a rough idea, key message, or article to turn into platform-specific post drafts.</p>
            <textarea id="idea" value={content} onChange={(event) => setContent(event.target.value)} placeholder="A new product launch, a lesson I learned, an idea I can't stop thinking about…" rows={6} maxLength={12000} />
            <div className="textarea-meta"><span>A few rough notes are enough to get started.</span><span>{content.length.toLocaleString()} / 12,000</span></div>

            <div className="audience-field">
              <label className="field-label" htmlFor="audience">Who are you talking to?</label>
              <input id="audience" value={audience} onChange={(event) => setAudience(event.target.value)} placeholder="e.g. first-time founders, design teams" maxLength={180} />
              <span className="input-hint">A little context helps us get the tone right.</span>
            </div>

            <div className="platform-field">
              <div className="platform-heading"><div><div className="field-label">Choose your platforms</div><div className="field-hint">The agents tailor a separate post draft to each platform you select.</div></div><span className="selection-count">{selected.length} selected</span></div>
              <div className="platform-grid">
                {platforms.map((platform) => <button type="button" key={platform.id} className={`platform-option ${selected.includes(platform.id) ? 'selected' : ''}`} onClick={() => togglePlatform(platform.id)} aria-pressed={selected.includes(platform.id)}>
                  <span className={`platform-mark mark-${platform.id}`}><PlatformIcon platform={platform.id} /></span><span className="platform-text"><b>{platform.name}</b><small>{platform.note}</small></span><span className="checkmark">✓</span>
                </button>)}
              </div>
            </div>

            {error && <div className="error-message" role="alert"><span>!</span>{error}</div>}
            <button className="generate-button" type="submit" disabled={loading}>
              {loading ? <><span className="button-spinner" /> Working on your drafts</> : <>Make it happen <span aria-hidden="true">↗</span></>}
            </button>
            <p className="form-note"><span>✳</span> Your idea guides every draft. Nothing is posted automatically.</p>
          </form>

          <aside className="results-panel" aria-live="polite">
            {drafts.length > 0 && message && <div className="manager-note" role="status">{message}</div>}
            {loading ? <div className="loading-state"><div className="loader-orbit"><span /><i /><b>S</b></div><div className="loading-kicker">AGENTS AT WORK</div><h2>{quotes[quoteIndex]}</h2><p>Our platform specialists are shaping and checking your post drafts.</p><div className="loading-progress"><i /></div><div className="loading-platforms">{selected.map((id) => <span key={id}>{platforms.find((platform) => platform.id === id)?.name}</span>)}</div><button className="cancel-button" type="button" onClick={cancelGeneration}>Cancel generation</button></div>
              : drafts.length ? <div className="draft-results"><div className="results-heading"><div className="section-kicker"><span>02</span> YOUR POST DRAFTS</div><h2>Ready for<br /><em>your review.</em></h2><p>Each agent tailors a draft to its platform. Review and copy the posts you want to use.</p></div><div className="draft-list">{drafts.map((draft, index) => <article className="draft-card" key={`${draft.platform}-${index}`}><div className="draft-topline"><span className={`draft-platform-mark mark-${draft.platform}`}>{draft.platform.toLowerCase() === 'instagram' ? <PlatformIcon platform="instagram" /> : platforms.find((item) => item.id === draft.platform.toLowerCase())?.mark ?? '✳'}</span><div><h3>{draft.platform}</h3><span className="draft-label">READY TO POST</span></div><button className="copy-button" onClick={() => void copyDraft(draft)} type="button" aria-label={`Copy ${draft.platform} draft`}>{copied === draft.platform ? 'Copied ✓' : 'Copy ↗'}</button></div><FormattedDraft text={draft.processed_content} /></article>)}</div><div className="results-footer"><span>✳</span> The agents create drafts for you to review. You decide what to post and when.</div></div>
              : message ? <div className="notice-state"><div className="notice-icon">✳</div><div className="loading-kicker">A NOTE FROM THE STUDIO</div><h2>Let’s take a different direction.</h2><p>{message}</p><button type="button" className="text-button" onClick={() => setMessage('')}>Back to your idea <span>↗</span></button></div>
                : <div className="empty-state"><div className="empty-art"><div className="empty-circle"><span>✳</span></div><div className="empty-paper"><i /><i /><i /><b>↗</b></div><div className="empty-spark spark-a">✳</div><div className="empty-spark spark-b">·</div></div><div className="loading-kicker">YOUR CONTENT TEAM</div><h2>Your next good thing<br />starts here.</h2><p>Share an idea or source and our AI agents will create platform-specific post drafts for you to review.</p><div className="empty-bottom"><span className="empty-line" /> YOUR IDEAS, READY TO SHARE <span className="empty-line" /></div></div>}
          </aside>
        </section>

        <section className="closing-note"><span className="closing-star">✳</span><div><h2>Bring the idea. We’ll shape the posts.</h2><p>Our agents prepare platform-ready drafts. You choose what to share.</p></div><span className="closing-flower">✿</span></section>
      </main>
      <footer className="footer"><a className="brand footer-brand" href="#top"><span className="brand-mark">s</span><span>storyloom<span className="brand-period">.</span></span></a><span>AI-assisted drafts for the ideas you want to share.</span><span>© 2026 STORYLOOM</span></footer>
    </div>
  )
}

export default App
