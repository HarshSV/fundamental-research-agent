import React, { useEffect, useRef, useState } from 'react';
import { API_BASE, getToken } from '../lib/api.js';

/* Anonymous, per-browser session id (this app has no per-user login — a
 * single shared SITE_PASSWORD, see auth.py) so the backend can persist chat
 * memory across reloads without a real user id. Generated once, kept in
 * localStorage. */
function getSessionId() {
  try {
    let id = localStorage.getItem('nv_chat_session_id');
    if (!id) {
      id = 'sess_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 10);
      localStorage.setItem('nv_chat_session_id', id);
    }
    return id;
  } catch (e) { return ''; }
}

/* ---------------------------------------------------------------------------
 * Ask Navrist — floating conversational assistant.
 *
 * Self-contained on purpose: no markdown/chart libraries in the project, so a
 * compact markdown renderer + an SVG chart renderer live here. The backend
 * (/api/v1/ask-navrist) may return chart specs inside ```chart fences; we split
 * those out and render real graphs inline. Voice is 100% browser-native:
 * SpeechRecognition for dictation, speechSynthesis for read-aloud — no keys.
 * ------------------------------------------------------------------------- */

const I = ({ children, s = 18 }) => (
  <svg viewBox="0 0 24 24" width={s} height={s} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);
const IconSpark = () => (<I s={20}><path d="M12 3l1.9 4.6L18.5 9 14 11l-2 4.6L10 11 5.5 9 10 7.6 12 3z" /><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z" /></I>);
const IconSend = () => (<I><path d="M22 2 11 13" /><path d="M22 2 15 22l-4-9-9-4 20-7z" /></I>);
const IconMic = () => (<I><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0 0 14 0M12 17v4" /></I>);
const IconClose = () => (<I><path d="M18 6 6 18M6 6l12 12" /></I>);
const IconSpeaker = () => (<I><path d="M11 5 6 9H2v6h4l5 4V5z" /><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14" /></I>);
const IconSpeakerOff = () => (<I><path d="M11 5 6 9H2v6h4l5 4V5z" /><path d="m22 9-6 6M16 9l6 6" /></I>);
const IconTrash = () => (<I s={16}><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></I>);

/* ------------------------- tiny inline markdown ------------------------- */
// Handles the inline span cases: **bold**, *italic*, `code`, [text](url).
function renderInline(text, keyPrefix) {
  const nodes = [];
  const re = /(\*\*([^*]+)\*\*)|(\*([^*]+)\*)|(`([^`]+)`)|(\[([^\]]+)\]\(([^)]+)\))/g;
  let last = 0, m, i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2] !== undefined) nodes.push(<strong key={`${keyPrefix}-b${i}`} className="font-semibold text-slate-100">{m[2]}</strong>);
    else if (m[4] !== undefined) nodes.push(<em key={`${keyPrefix}-i${i}`} className="italic">{m[4]}</em>);
    else if (m[6] !== undefined) nodes.push(<code key={`${keyPrefix}-c${i}`} className="px-1 py-0.5 rounded bg-slate-800 text-blue-200 font-mono text-[12px]">{m[6]}</code>);
    else if (m[8] !== undefined) nodes.push(<a key={`${keyPrefix}-a${i}`} href={m[9]} target="_blank" rel="noreferrer" className="text-blue-400 underline hover:text-blue-300">{m[8]}</a>);
    last = re.lastIndex; i++;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

// Block-level markdown: headings, bullet/numbered lists, tables, paragraphs.
function Markdown({ text }) {
  const lines = (text || '').split('\n');
  const blocks = [];
  let i = 0;
  const isTableSep = (s) => /^\s*\|?[\s:|-]+\|?\s*$/.test(s) && s.includes('-');

  while (i < lines.length) {
    let line = lines[i];

    if (!line.trim()) { i++; continue; }

    // Table: header row + separator + body rows
    if (line.includes('|') && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const cells = (r) => r.replace(/^\s*\|/, '').replace(/\|\s*$/, '').split('|').map((c) => c.trim());
      const header = cells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) { rows.push(cells(lines[i])); i++; }
      blocks.push(
        <div key={`t${i}`} className="overflow-x-auto my-2">
          <table className="w-full text-[12px] border-collapse">
            <thead><tr>{header.map((h, k) => <th key={k} className="text-left font-semibold text-slate-300 border-b border-slate-700 px-2 py-1.5">{renderInline(h, `th${i}${k}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, ci) => <td key={ci} className="border-b border-slate-800 px-2 py-1.5 text-slate-300">{renderInline(c, `td${i}${ri}${ci}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      );
      continue;
    }

    // Headings
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      const lvl = h[1].length;
      const sz = lvl <= 1 ? 'text-[15px]' : lvl === 2 ? 'text-[14px]' : 'text-[13px]';
      blocks.push(<div key={`h${i}`} className={`font-heading font-bold text-slate-100 ${sz} mt-2 mb-1`}>{renderInline(h[2], `h${i}`)}</div>);
      i++; continue;
    }

    // Bullet list
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*]\s+/, '')); i++; }
      blocks.push(<ul key={`ul${i}`} className="list-disc pl-5 space-y-0.5 my-1">{items.map((it, k) => <li key={k} className="text-slate-300 leading-relaxed">{renderInline(it, `li${i}${k}`)}</li>)}</ul>);
      continue;
    }

    // Numbered list
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+\.\s+/, '')); i++; }
      blocks.push(<ol key={`ol${i}`} className="list-decimal pl-5 space-y-0.5 my-1">{items.map((it, k) => <li key={k} className="text-slate-300 leading-relaxed">{renderInline(it, `oli${i}${k}`)}</li>)}</ol>);
      continue;
    }

    // Paragraph (accumulate consecutive non-blank, non-special lines)
    const para = [line];
    i++;
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|\s*[-*]\s|\s*\d+\.\s)/.test(lines[i]) && !(lines[i].includes('|'))) { para.push(lines[i]); i++; }
    blocks.push(<p key={`p${i}`} className="text-slate-300 leading-relaxed my-1">{renderInline(para.join(' '), `p${i}`)}</p>);
  }
  return <div className="space-y-0.5">{blocks}</div>;
}

/* ------------------------------ SVG chart ------------------------------ */
function MiniChart({ spec }) {
  try {
    const series = spec.series || [];
    const pts = series[0]?.points || [];
    if (!pts.length) return null;
    const W = 300, H = 150, pad = { l: 34, r: 10, t: 8, b: 22 };
    const iw = W - pad.l - pad.r, ih = H - pad.t - pad.b;
    const allY = series.flatMap((s) => (s.points || []).map((p) => Number(p.y))).filter((v) => !isNaN(v));
    const maxY = Math.max(...allY, 0), minY = Math.min(...allY, 0);
    const span = maxY - minY || 1;
    const xs = pts.map((p) => String(p.x));
    const xAt = (k) => pad.l + (xs.length === 1 ? iw / 2 : (k / (xs.length - 1)) * iw);
    const yAt = (v) => pad.t + ih - ((Number(v) - minY) / span) * ih;
    const colors = ['#3b82f6', '#10b981', '#f59e0b'];

    return (
      <div className="my-2 rounded-lg border border-slate-800 bg-slate-950 p-2">
        {spec.title && <div className="text-[11px] font-semibold text-slate-300 mb-1 px-1">{spec.title}</div>}
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={spec.title || 'chart'}>
          {[0, 0.5, 1].map((f, k) => {
            const y = pad.t + ih - f * ih;
            return <g key={k}><line x1={pad.l} y1={y} x2={W - pad.r} y2={y} stroke="#1e293b" strokeWidth="1" /><text x={pad.l - 4} y={y + 3} textAnchor="end" fontSize="8" fill="#64748b">{Math.round(minY + f * span)}</text></g>;
          })}
          {spec.type === 'line'
            ? series.map((s, si) => (
                <polyline key={si} fill="none" stroke={colors[si % colors.length]} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                  points={(s.points || []).map((p, k) => `${xAt(k)},${yAt(p.y)}`).join(' ')} />
              ))
            : pts.map((p, k) => {
                const bw = Math.max(6, (iw / xs.length) * 0.55);
                const y = yAt(p.y), zero = yAt(0);
                return <rect key={k} x={xAt(k) - bw / 2} y={Math.min(y, zero)} width={bw} height={Math.abs(zero - y) || 1} rx="2" fill={colors[0]} />;
              })}
          {xs.map((x, k) => <text key={k} x={xAt(k)} y={H - 6} textAnchor="middle" fontSize="8" fill="#64748b">{x}</text>)}
        </svg>
      </div>
    );
  } catch (e) { return null; }
}

// Split an assistant message into text + chart segments.
function MessageBody({ content }) {
  const parts = [];
  const re = /```chart\s*([\s\S]*?)```/g;
  let last = 0, m, i = 0;
  while ((m = re.exec(content)) !== null) {
    if (m.index > last) parts.push({ type: 'md', text: content.slice(last, m.index) });
    try { parts.push({ type: 'chart', spec: JSON.parse(m[1].trim()) }); }
    catch (e) { parts.push({ type: 'md', text: '```\n' + m[1] + '\n```' }); }
    last = re.lastIndex; i++;
  }
  if (last < content.length) parts.push({ type: 'md', text: content.slice(last) });
  return (
    <div>
      {parts.map((p, k) => p.type === 'chart'
        ? <MiniChart key={k} spec={p.spec} />
        : <Markdown key={k} text={p.text} />)}
    </div>
  );
}

/* ------------------------------ voice hooks ----------------------------- */
function getRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.lang = 'en-IN';
  r.interimResults = true;
  r.continuous = false;
  return r;
}

/* -------------------------------- widget -------------------------------- */
const WELCOME = { role: 'assistant', content: "Hi — I'm **Ask Navrist**. Ask me about a company on screen, any financial ratio, or how this terminal works. I can also draw quick charts and take voice input." };

export default function AskNavrist({ context, symbol }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([WELCOME]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(false);
  const scrollRef = useRef(null);
  const recRef = useRef(null);
  const baseInputRef = useRef('');
  const sessionIdRef = useRef(getSessionId());

  const canVoice = typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
  const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window;

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, open]);

  const speakText = (text) => {
    if (!canSpeak) return;
    try {
      // Read a cleaned version — strip markdown symbols and chart JSON.
      const clean = text.replace(/```chart[\s\S]*?```/g, ' (chart shown) ').replace(/[#*`_>|-]/g, ' ').replace(/\s+/g, ' ').trim();
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(clean.slice(0, 600));
      u.lang = 'en-IN';
      window.speechSynthesis.speak(u);
    } catch (e) { /* ignore */ }
  };

  const send = async (textArg) => {
    const text = (textArg ?? input).trim();
    if (!text || sending) return;
    const next = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setInput('');
    setSending(true);
    try {
      const token = getToken();
      const res = await fetch(`${API_BASE}/api/v1/ask-navrist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({
          messages: next.filter((m) => m !== WELCOME).map((m) => ({ role: m.role, content: m.content })),
          context: context || '',
          session_id: sessionIdRef.current,
          symbol: symbol || '',
        }),
      });
      const data = await res.json();
      const reply = data?.reply || "I couldn't generate a response.";
      setMessages((cur) => [...cur, { role: 'assistant', content: reply }]);
      if (speak) speakText(reply);
    } catch (e) {
      setMessages((cur) => [...cur, { role: 'assistant', content: 'Network error — please try again.' }]);
    } finally {
      setSending(false);
    }
  };

  const toggleMic = () => {
    if (!canVoice) return;
    if (listening) { recRef.current && recRef.current.stop(); return; }
    const r = getRecognition();
    if (!r) return;
    recRef.current = r;
    baseInputRef.current = input ? input + ' ' : '';
    r.onresult = (e) => {
      let txt = '';
      for (let k = 0; k < e.results.length; k++) txt += e.results[k][0].transcript;
      setInput(baseInputRef.current + txt);
    };
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  };

  const reset = () => { window.speechSynthesis && window.speechSynthesis.cancel(); setMessages([WELCOME]); };

  return (
    <>
      {/* Launcher */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed z-[60] bottom-5 right-5 h-14 pl-4 pr-5 rounded-full bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-600/25 flex items-center gap-2 font-semibold text-[14px] transition-transform hover:scale-[1.03] nv-float2"
          aria-label="Open Ask Navrist"
        >
          <IconSpark /> Ask Navrist
        </button>
      )}

      {/* Panel */}
      {open && (
        <div className="fixed z-[60] bottom-0 right-0 sm:bottom-5 sm:right-5 w-full sm:w-[400px] h-[100dvh] sm:h-[600px] sm:max-h-[calc(100vh-40px)] flex flex-col nv-card sm:rounded-2xl overflow-hidden shadow-2xl border-slate-700">
          {/* Header */}
          <div className="flex items-center justify-between px-4 h-14 border-b border-slate-800 flex-shrink-0 bg-slate-900">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-blue-600 text-white grid place-items-center"><IconSpark /></div>
              <div className="leading-tight">
                <div className="font-heading font-bold text-slate-100 text-[14px]">Ask Navrist</div>
                <div className="text-[10px] text-slate-500">{sending ? 'Thinking…' : context ? 'Company loaded · ready' : 'AI assistant'}</div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {canSpeak && (
                <button onClick={() => { setSpeak((v) => { if (v) window.speechSynthesis.cancel(); return !v; }); }}
                  className={`nv-icon-btn w-8 h-8 !border-0 ${speak ? 'text-blue-400' : 'text-slate-500'}`}
                  title={speak ? 'Read replies aloud: on' : 'Read replies aloud: off'}>
                  {speak ? <IconSpeaker /> : <IconSpeakerOff />}
                </button>
              )}
              <button onClick={reset} className="nv-icon-btn w-8 h-8 !border-0 text-slate-500" title="Clear chat"><IconTrash /></button>
              <button onClick={() => setOpen(false)} className="nv-icon-btn w-8 h-8 !border-0 text-slate-400" title="Close"><IconClose /></button>
            </div>
          </div>

          {/* Messages */}
          <div ref={scrollRef} className="flex-1 overflow-y-auto px-3.5 py-3 space-y-3 bg-slate-950/40">
            {messages.map((m, k) => (
              <div key={k} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-[13px] ${
                  m.role === 'user'
                    ? 'bg-blue-600 text-white rounded-br-md'
                    : 'bg-slate-900 border border-slate-800 text-slate-200 rounded-bl-md'
                }`}>
                  {m.role === 'user' ? <span className="whitespace-pre-wrap">{m.content}</span> : <MessageBody content={m.content} />}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-slate-900 border border-slate-800 rounded-2xl rounded-bl-md px-4 py-3 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-500 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="border-t border-slate-800 p-2.5 flex-shrink-0 bg-slate-900">
            <div className="flex items-end gap-2 bg-slate-950 border border-slate-800 rounded-2xl px-2.5 py-1.5 focus-within:border-blue-500/50 transition-colors">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                rows={1}
                placeholder={listening ? 'Listening…' : 'Ask anything…'}
                className="flex-1 bg-transparent outline-none text-slate-100 placeholder:text-slate-500 text-[13px] resize-none max-h-24 py-1.5 min-w-0"
                style={{ height: 'auto' }}
              />
              {canVoice && (
                <button onClick={toggleMic}
                  className={`w-9 h-9 rounded-xl grid place-items-center flex-shrink-0 transition-colors ${listening ? 'bg-red-500/15 text-red-400 animate-pulse' : 'text-slate-400 hover:text-slate-200 hover:bg-slate-850'}`}
                  title={listening ? 'Stop dictation' : 'Voice input'}>
                  <IconMic />
                </button>
              )}
              <button onClick={() => send()} disabled={!input.trim() || sending}
                className="w-9 h-9 rounded-xl grid place-items-center flex-shrink-0 bg-blue-600 text-white disabled:opacity-40 disabled:cursor-default hover:bg-blue-700 transition-colors"
                title="Send">
                <IconSend />
              </button>
            </div>
            <div className="text-[9px] text-slate-600 text-center mt-1.5">Ask Navrist can make mistakes · Not investment advice</div>
          </div>
        </div>
      )}
    </>
  );
}
