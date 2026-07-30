'use client';

import { useState, useRef, useEffect } from 'react';
import styles from './sandbox-agent.module.css';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080';

export default function SandboxAgentPage() {
  // ─── Session State ───
  const [sessionId, setSessionId] = useState(null);
  const [sessionState, setSessionState] = useState(null);
  const [schemeId, setSchemeId] = useState('sandbox-demo');

  // ─── Chat State ───
  const [messages, setMessages] = useState([]); // [{ role: 'user'|'agent', text, toolCalls? }]
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // ─── Agent Internals ───
  const [turns, setTurns] = useState([]); // [{ turnNumber, toolCalls, internalLog }]

  const chatEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Focus input after loading
  useEffect(() => {
    if (!isLoading && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isLoading]);

  // ─── Init Session ───
  const handleInit = async () => {
    try {
      setIsLoading(true);
      const res = await fetch(`${API_BASE_URL}/api/agent/init`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scheme_id: schemeId }),
      });
      const data = await res.json();
      if (data.success) {
        setSessionId(data.session_id);
        setSessionState(data.session_state);
        setMessages([]);
        setTurns([]);
      } else {
        alert('Failed to init session: ' + (data.detail || 'Unknown error'));
      }
    } catch (err) {
      alert('Failed to connect to agent service: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // ─── Send Message ───
  const handleSend = async () => {
    const msg = inputText.trim();
    if (!msg || isLoading || !sessionId) return;

    setInputText('');
    setMessages(prev => [...prev, { role: 'user', text: msg }]);
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/agent/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: msg }),
      });
      const data = await res.json();

      if (data.success) {
        // Add agent message
        setMessages(prev => [...prev, {
          role: 'agent',
          text: data.agent_response,
          toolCalls: data.tool_calls || [],
        }]);

        // Update session state
        setSessionState(data.session_state);

        // Add turn to internals
        setTurns(prev => [...prev, {
          turnNumber: prev.length + 1,
          toolCalls: data.tool_calls || [],
          internalLog: data.internal_log || [],
          pendingConfirmation: data.pending_confirmation,
        }]);
      } else {
        setMessages(prev => [...prev, {
          role: 'agent',
          text: data.detail || 'Something went wrong. Please try again.',
          toolCalls: [],
        }]);
      }
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'agent',
        text: `Connection error: ${err.message}`,
        toolCalls: [],
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ─── Helpers ───
  const getStatusClass = (status) => {
    switch (status) {
      case 'COMPLETED': return styles.queueItemCompleted;
      case 'ACTIVE': return styles.queueItemActive;
      default: return styles.queueItemPending;
    }
  };

  const getStatusBadgeClass = (status) => {
    switch (status) {
      case 'COMPLETED': return styles.statusCompleted;
      case 'ACTIVE': return styles.statusActive;
      default: return styles.statusPending;
    }
  };

  const getToolBadgeClass = (status) => {
    switch (status) {
      case 'success': return styles.badgeSuccess;
      case 'error':
      case 'validation_error': return styles.badgeError;
      case 'needs_confirmation':
      case 'needs_clarification':
      case 'ambiguous': return styles.badgeWarning;
      default: return styles.badgeInfo;
    }
  };

  const formatFieldKey = (key) => {
    return key.replace(/^doc_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  };

  // ─── Init Screen ───
  if (!sessionId) {
    return (
      <div className={styles.initScreen}>
        <div className={styles.initTitle}>Agent Sandbox</div>
        <div className={styles.initSubtitle}>
          Test the agentic document capture co-pilot. Select a scheme to initialize a session with mock data.
        </div>
        <select
          className={styles.initSelect}
          value={schemeId}
          onChange={(e) => setSchemeId(e.target.value)}
        >
          <option value="sandbox-demo">Sandbox Demo (Aadhaar + PAN + Udyam)</option>
          <option value="mudra-grocery">Mudra Grocery (Full KYC)</option>
        </select>
        <button className={styles.initBtn} onClick={handleInit} disabled={isLoading}>
          {isLoading ? 'Initializing...' : 'Start Agent Session'}
        </button>
      </div>
    );
  }

  // ─── Main 3-Panel Layout ───
  return (
    <div className={styles.container}>
      {/* ═══ LEFT PANEL — Session State ═══ */}
      <div className={styles.panelLeft}>
        <div className={styles.panelHeader}>
          <span>📋</span> Session State
        </div>
        <div className={styles.panelBody}>
          {/* Document Queue */}
          <div className={styles.sectionTitle}>Document Queue</div>
          {sessionState?.document_queue?.map((item, i) => (
            <div key={i} className={getStatusClass(item.status)}>
              <div className={styles.queueText}>
                <div className={styles.queueDocTitle}>{item.doc_title}</div>
                <div className={styles.queuePartName}>{item.part_name}</div>
              </div>
              <span className={getStatusBadgeClass(item.status)}>
                {item.status === 'COMPLETED' ? '✓' : item.status === 'ACTIVE' ? '●' : '○'}
              </span>
            </div>
          ))}

          {/* Pending Confirmation */}
          {sessionState?.pending_confirmation && (
            <>
              <div className={styles.sectionTitle}>Pending Confirmation</div>
              <div className={styles.confirmationBanner}>
                ⚠️ {sessionState.pending_confirmation.type}: {sessionState.pending_confirmation.doc_title} — {sessionState.pending_confirmation.part_name}
              </div>
            </>
          )}

          {/* Extracted Data */}
          <div className={styles.sectionTitle}>Extracted Data</div>
          {sessionState?.extracted_data && Object.keys(sessionState.extracted_data).length > 0 ? (
            Object.entries(sessionState.extracted_data).map(([key, data]) => (
              <div key={key} className={styles.fieldRow}>
                <span className={styles.fieldKey}>{formatFieldKey(key)}</span>
                <span className={data.manually_overridden ? styles.fieldOverridden : styles.fieldValue}>
                  {typeof data.value === 'object' ? JSON.stringify(data.value) : String(data.value)}
                  {data.manually_overridden && <span className={styles.overrideBadge}>EDITED</span>}
                </span>
              </div>
            ))
          ) : (
            <div style={{ color: '#475569', fontSize: '0.78rem', padding: '8px 0' }}>
              No data extracted yet
            </div>
          )}
        </div>
      </div>

      {/* ═══ CENTER PANEL — Chat ═══ */}
      <div className={styles.panelCenter}>
        <div className={styles.chatHeader}>
          <div>
            <div className={styles.chatTitle}>Agent Chat</div>
            <div className={styles.chatSubtitle}>
              Session: {sessionId?.slice(0, 8)}... | Scheme: {sessionState?.scheme_id}
            </div>
          </div>
          <button
            onClick={() => { setSessionId(null); setSessionState(null); setMessages([]); setTurns([]); }}
            style={{
              background: '#1e293b', color: '#94a3b8', border: '1px solid #334155',
              borderRadius: '8px', padding: '6px 14px', fontSize: '0.78rem', cursor: 'pointer',
              fontWeight: 600, transition: 'all 0.15s'
            }}
          >
            Reset
          </button>
        </div>

        <div className={styles.chatMessages}>
          {messages.length === 0 && !isLoading && (
            <div style={{
              textAlign: 'center', color: '#475569', padding: '60px 20px',
              fontSize: '0.88rem', lineHeight: 1.6,
            }}>
              <div style={{ fontSize: '2rem', marginBottom: '12px' }}>🤖</div>
              <div style={{ fontWeight: 600, color: '#64748b', marginBottom: '6px' }}>
                Agent is ready
              </div>
              <div>
                Try: &quot;Switch to PAN card&quot; · &quot;My pincode is 126112&quot; · &quot;Submit my application&quot;
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i}>
              <div className={msg.role === 'user' ? styles.messageUser : styles.messageAgent}>
                {msg.text}
              </div>
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '6px', paddingLeft: '4px' }}>
                  {msg.toolCalls.map((tc, j) => (
                    <span key={j} className={getToolBadgeClass(tc.validation?.status)}>
                      🔧 {tc.tool_name}
                      {tc.signal && (
                        <span className={styles.signalBadge} style={{ marginLeft: '6px' }}>
                          → {tc.signal.type}
                        </span>
                      )}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}

          {isLoading && (
            <div className={styles.typingIndicator}>
              <div className={styles.typingDot}></div>
              <div className={styles.typingDot}></div>
              <div className={styles.typingDot}></div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <div className={styles.chatInputBar}>
          <input
            ref={inputRef}
            className={styles.chatInput}
            type="text"
            placeholder="Type a message to the agent..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
          />
          <button
            className={styles.chatSendBtn}
            onClick={handleSend}
            disabled={isLoading || !inputText.trim()}
          >
            Send
          </button>
        </div>
      </div>

      {/* ═══ RIGHT PANEL — Agent Internals ═══ */}
      <div className={styles.panelRight}>
        <div className={styles.panelHeader}>
          <span>⚙️</span> Agent Internals
        </div>
        <div className={styles.panelBody}>
          {turns.length === 0 && (
            <div style={{ color: '#475569', fontSize: '0.78rem', textAlign: 'center', padding: '20px 0' }}>
              No turns yet. Send a message to see agent internals.
            </div>
          )}

          {[...turns].reverse().map((turn, i) => (
            <TurnCard key={turn.turnNumber} turn={turn} defaultOpen={i === 0} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Turn Card Component (Accordion) ───
function TurnCard({ turn, defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  const mainTool = turn.toolCalls?.[0];
  const toolName = mainTool?.tool_name || 'text_response';
  const toolStatus = mainTool?.validation?.status || 'info';

  return (
    <div className={styles.turnCard}>
      <div className={styles.turnHeader} onClick={() => setIsOpen(!isOpen)}>
        <div>
          <span className={styles.turnNumber}>Turn {turn.turnNumber}</span>
          {' '}
          <span className={styles.turnToolName}>{toolName}</span>
        </div>
        <span style={{ color: '#475569', fontSize: '0.85rem' }}>
          {isOpen ? '▼' : '▶'}
        </span>
      </div>

      {isOpen && (
        <div className={styles.turnBody}>
          {turn.internalLog?.map((log, i) => (
            <div key={i} className={styles.logStep}>
              <div className={styles.logStepLabel}>{log.step}</div>
              <div className={styles.logStepValue}>
                {log.step === 'system_prompt_built' && (
                  <span>Length: {log.system_prompt_length} chars ({log.elapsed_ms}ms)</span>
                )}
                {log.step === 'gemini_called' && (
                  <span>Model: {log.model} ({log.latency_ms}ms)</span>
                )}
                {log.step === 'function_call_received' && (
                  <>
                    <div>Tool: <strong>{log.tool_name}</strong></div>
                    <div className={styles.logJson}>
                      {JSON.stringify(log.arguments, null, 2)}
                    </div>
                  </>
                )}
                {log.step === 'tool_executed' && (
                  <>
                    <div>Status: <strong style={{
                      color: log.result_status === 'success' ? '#4ade80' :
                             log.result_status === 'error' || log.result_status === 'validation_error' ? '#f87171' :
                             '#fbbf24'
                    }}>{log.result_status}</strong> ({log.elapsed_ms}ms)</div>
                    <div style={{ marginTop: '4px', color: '#94a3b8' }}>{log.result_message}</div>
                    {log.signal && (
                      <div className={styles.logJson}>
                        <div style={{ color: '#a78bfa', marginBottom: '4px', fontWeight: 700 }}>
                          Signal: {log.signal.type}
                        </div>
                        {JSON.stringify(log.signal.payload, null, 2)}
                      </div>
                    )}
                  </>
                )}
                {log.step === 'gemini_final_response' && (
                  <span>{log.text} ({log.latency_ms}ms)</span>
                )}
                {log.step === 'text_response' && (
                  <span>{log.text}</span>
                )}
                {log.step === 'gemini_error' && (
                  <span style={{ color: '#f87171' }}>{log.error}</span>
                )}
              </div>
            </div>
          ))}

          {/* Tool calls summary */}
          {turn.toolCalls?.length > 0 && (
            <div className={styles.logStep}>
              <div className={styles.logStepLabel}>Tool Calls</div>
              <div className={styles.logJson}>
                {JSON.stringify(turn.toolCalls, null, 2)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
