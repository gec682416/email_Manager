import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    try {
      const data = JSON.parse(text);
      throw new Error(data.detail || text || response.statusText);
    } catch (err) {
      if (err instanceof SyntaxError) {
        throw new Error(text || response.statusText);
      }
      throw err;
    }
  }
  return response.json();
}

function App() {
  const [dashboard, setDashboard] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [emails, setEmails] = useState([]);
  const [events, setEvents] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [reminders, setReminders] = useState([]);
  const [conflicts, setConflicts] = useState([]);
  const [selectedEmail, setSelectedEmail] = useState(null);
  const [editingEvent, setEditingEvent] = useState(null);
  const [question, setQuestion] = useState('我这周有哪些面试？');
  const [answer, setAnswer] = useState('');
  const [agentMeta, setAgentMeta] = useState(null);
  const [agentRun, setAgentRun] = useState(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const [accountForm, setAccountForm] = useState({ email_address: '', app_password: '', imap_host: 'imap.163.com', imap_port: 993 });

  async function refresh() {
    const [d, a, m, e, t, r, c] = await Promise.all([
      api('/api/dashboard'),
      api('/api/mail-accounts'),
      api('/api/emails'),
      api('/api/events'),
      api('/api/tasks'),
      api('/api/reminders'),
      api('/api/conflicts'),
    ]);
    setDashboard(d);
    setAccounts(a);
    setEmails(m);
    setEvents(e);
    setTasks(t);
    setReminders(r);
    setConflicts(c);
  }

  useEffect(() => {
    refresh().catch((err) => setNotice(err.message));
  }, []);

  async function saveAccount(e) {
    e.preventDefault();
    setLoading(true);
    try {
      await api('/api/mail-accounts', { method: 'POST', body: JSON.stringify(accountForm) });
      setAccountForm({ ...accountForm, app_password: '' });
      setNotice('邮箱配置已保存');
      await refresh();
    } catch (err) {
      setNotice(`保存失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function syncFirstAccount() {
    if (!accounts.length) {
      setNotice('请先配置网易邮箱账号和授权码');
      return;
    }
    setLoading(true);
    setNotice('正在同步邮件，这可能需要几十秒...');
    try {
      const result = await api(`/api/mail-accounts/${accounts[0].id}/sync`, { method: 'POST' });
      setNotice(`同步完成：拉取 ${result.fetched} 封，处理 ${result.processed} 封`);
      await refresh();
    } catch (err) {
      setNotice(`同步失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function openEmail(id) {
    try {
      setSelectedEmail(await api(`/api/emails/${id}`));
    } catch (err) {
      setNotice(err.message);
    }
  }

  async function deleteSelectedEmail() {
    if (!selectedEmail) return;
    setLoading(true);
    try {
      await api(`/api/emails/${selectedEmail.id}/local-copy`, { method: 'DELETE' });
      setSelectedEmail(null);
      setNotice('已删除本系统本地邮件副本；网易邮箱服务器邮件不会被删除');
      await refresh();
    } catch (err) {
      setNotice(`删除失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function updateEvent(id, action) {
    await api(`/api/events/${id}/${action}`, { method: 'PATCH' });
    await refresh();
  }

  async function saveEvent(e) {
    e.preventDefault();
    if (!editingEvent) return;
    setLoading(true);
    try {
      const payload = {
        title: editingEvent.title,
        company: editingEvent.company || null,
        start_time: toIsoFromLocalInput(editingEvent.start_time),
        end_time: toIsoFromLocalInput(editingEvent.end_time),
        location: editingEvent.location || null,
        meeting_link: editingEvent.meeting_link || null,
        description: editingEvent.description || '',
        status: editingEvent.status || 'draft',
      };
      const updated = await api(`/api/events/${editingEvent.id}`, { method: 'PATCH', body: JSON.stringify(payload) });
      setEditingEvent(updated);
      setNotice('事件已更新，冲突和 ICS 已重新生成');
      await refresh();
    } catch (err) {
      setNotice(`事件更新失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function recheckConflicts() {
    setLoading(true);
    try {
      await api('/api/conflicts/recheck', { method: 'POST' });
      setNotice('冲突检测已重新执行');
      await refresh();
    } catch (err) {
      setNotice(`冲突检测失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function cleanupRaw() {
    setLoading(true);
    try {
      const result = await api('/api/maintenance/cleanup-raw', { method: 'POST' });
      setNotice(`清理完成：${result.emails_cleaned} 封过期本地原文，未删除服务器邮件`);
      await refresh();
    } catch (err) {
      setNotice(`清理失败：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  async function askAgent(e) {
    e.preventDefault();
    setLoading(true);
    try {
      const data = await api('/api/agent/query', { method: 'POST', body: JSON.stringify({ question }) });
      setAnswer(data.answer);
      setAgentMeta(data);
      setAgentRun(null);
    } catch (err) {
      setAnswer(`查询失败：${err.message}`);
      setAgentMeta(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadAgentRun() {
    if (!agentMeta?.run_id) return;
    try {
      setAgentRun(await api(`/api/agent-runs/${agentMeta.run_id}`));
    } catch (err) {
      setNotice(`读取 Agent Run 失败：${err.message}`);
    }
  }

  const lastSync = dashboard?.last_sync_at ? new Date(dashboard.last_sync_at).toLocaleString() : '尚未同步';

  return (
    <main className="app">
      <header className="topbar">
        <div>
          <h1>Email Manager Agent</h1>
          <p>单用户本地版 · 网易邮箱手动同步 · 内部日历</p>
        </div>
        <button className="primary" onClick={syncFirstAccount} disabled={loading}>同步邮件</button>
      </header>

      {notice && <div className="notice">{notice}</div>}

      <section className="grid metrics">
        <Metric label="最近同步" value={lastSync} />
        <Metric label="邮件" value={dashboard?.email_count ?? 0} />
        <Metric label="日程" value={dashboard?.event_count ?? 0} />
        <Metric label="待办" value={dashboard?.task_count ?? 0} />
        <Metric label="冲突" value={dashboard?.conflict_count ?? 0} />
        <Metric label="待确认" value={dashboard?.pending_review_count ?? 0} />
      </section>

      <section className="panel">
        <h2>邮箱配置</h2>
        <form className="account-form" onSubmit={saveAccount}>
          <input placeholder="网易邮箱地址" value={accountForm.email_address} onChange={(e) => setAccountForm({ ...accountForm, email_address: e.target.value })} />
          <input placeholder="客户端授权码" type="password" value={accountForm.app_password} onChange={(e) => setAccountForm({ ...accountForm, app_password: e.target.value })} />
          <input placeholder="IMAP Host" value={accountForm.imap_host} onChange={(e) => setAccountForm({ ...accountForm, imap_host: e.target.value })} />
          <button disabled={loading}>保存</button>
        </form>
        <p className="muted">已配置账号：{accounts.map((a) => a.email_address).join(', ') || '无'}</p>
      </section>

      <section className="layout">
        <div className="panel">
          <h2>邮件</h2>
          <div className="list">
            {emails.map((email) => (
              <button key={email.id} className="list-item" onClick={() => openEmail(email.id)}>
                <strong>{email.subject || '(无标题)'}</strong>
                <span>{email.from_email} · {email.category || '未分类'} · {email.confidence ? Math.round(email.confidence * 100) + '%' : ''}</span>
                <small>{email.snippet}</small>
              </button>
            ))}
          </div>
        </div>

        <div className="panel">
          <h2>邮件详情</h2>
          {selectedEmail ? (
            <article className="detail">
              <h3>{selectedEmail.subject}</h3>
              <p>{selectedEmail.from_email}</p>
              <div className="actions">
                <button onClick={deleteSelectedEmail} disabled={loading}>删除本地副本</button>
              </div>
              <pre>{selectedEmail.clean_text}</pre>
            </article>
          ) : <p className="muted">选择一封邮件查看详情。</p>}
        </div>
      </section>

      <section className="layout">
        <div className="panel">
          <div className="section-head">
            <h2>内部日历</h2>
            <a className="link-button" href={`${API_BASE}/api/calendar.ics`}>下载 ICS</a>
          </div>
          <div className="list">
            {events.map((event) => (
              <div className={`event ${event.status === 'conflict' ? 'danger' : ''}`} key={event.id}>
                <strong>{event.title}</strong>
                <span>{event.start_time ? new Date(event.start_time).toLocaleString() : '时间待确认'} · {event.status}</span>
                <small>{event.location || event.meeting_link || event.description}</small>
                {!!event.evidence?.length && <small>证据：{event.evidence[0]}</small>}
                {!!event.conflicts?.length && <small className="danger-text">{event.conflicts[0].description}</small>}
                <div className="actions">
                  <button onClick={() => setEditingEvent(normalizeEventForEdit(event))}>编辑</button>
                  <button onClick={() => updateEvent(event.id, 'confirm')}>确认</button>
                  <button onClick={() => updateEvent(event.id, 'ignore')}>忽略</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <h2>待办</h2>
            <button onClick={recheckConflicts} disabled={loading}>重检冲突</button>
          </div>
          <div className="list">
            {tasks.map((task) => (
              <div className="event" key={task.id}>
                <strong>{task.title}</strong>
                <span>{task.due_at ? new Date(task.due_at).toLocaleString() : '无截止时间'} · {task.priority}</span>
                <small>{task.description}</small>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="layout">
        <div className="panel">
          <h2>冲突提醒</h2>
          <div className="list compact">
            {conflicts.map((conflict) => (
              <div className="event danger" key={conflict.id}>
                <strong>{conflict.conflict_type}</strong>
                <span>{conflict.severity} · {conflict.status}</span>
                <small>{conflict.description}</small>
              </div>
            ))}
            {!conflicts.length && <p className="muted">暂无打开的日程冲突。</p>}
          </div>
        </div>

        <div className="panel">
          <div className="section-head">
            <h2>提醒</h2>
            <button onClick={cleanupRaw} disabled={loading}>清理过期原文</button>
          </div>
          <div className="list compact">
            {reminders.map((reminder) => (
              <div className="event" key={reminder.id}>
                <strong>{reminder.target_type} #{reminder.target_id}</strong>
                <span>{new Date(reminder.remind_at).toLocaleString()} · {reminder.status}</span>
                <small>{reminder.channel}</small>
              </div>
            ))}
            {!reminders.length && <p className="muted">暂无提醒。</p>}
          </div>
        </div>
      </section>

      {editingEvent && (
        <section className="panel">
          <div className="section-head">
            <h2>事件复核</h2>
            <button onClick={() => setEditingEvent(null)}>关闭</button>
          </div>
          <form className="event-form" onSubmit={saveEvent}>
            <input placeholder="标题" value={editingEvent.title || ''} onChange={(e) => setEditingEvent({ ...editingEvent, title: e.target.value })} />
            <input placeholder="公司" value={editingEvent.company || ''} onChange={(e) => setEditingEvent({ ...editingEvent, company: e.target.value })} />
            <input type="datetime-local" value={editingEvent.start_time || ''} onChange={(e) => setEditingEvent({ ...editingEvent, start_time: e.target.value })} />
            <input type="datetime-local" value={editingEvent.end_time || ''} onChange={(e) => setEditingEvent({ ...editingEvent, end_time: e.target.value })} />
            <input placeholder="地点" value={editingEvent.location || ''} onChange={(e) => setEditingEvent({ ...editingEvent, location: e.target.value })} />
            <input placeholder="会议链接" value={editingEvent.meeting_link || ''} onChange={(e) => setEditingEvent({ ...editingEvent, meeting_link: e.target.value })} />
            <select value={editingEvent.status || 'draft'} onChange={(e) => setEditingEvent({ ...editingEvent, status: e.target.value })}>
              <option value="draft">draft</option>
              <option value="confirmed">confirmed</option>
              <option value="needs_review">needs_review</option>
              <option value="ignored">ignored</option>
            </select>
            <button disabled={loading}>保存事件</button>
          </form>
          {!!editingEvent.evidence?.length && <pre className="answer">{editingEvent.evidence.join('\n')}</pre>}
        </section>
      )}

      <section className="panel">
        <h2>Agent 查询</h2>
        <form className="agent-form" onSubmit={askAgent}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} />
          <button disabled={loading}>提问</button>
        </form>
        {answer && <pre className="answer">{answer}</pre>}
        {agentMeta && (
          <div className="agent-meta">
            <div className="meta-row">
              <span>Run #{agentMeta.run_id || '-'}</span>
              <span>{agentMeta.model_name || 'unknown'}</span>
              <button onClick={loadAgentRun}>查看日志</button>
            </div>
            {!!agentMeta.source_refs?.length && (
              <div>
                <h3>来源</h3>
                <div className="chips">
                  {agentMeta.source_refs.map((ref, index) => (
                    <button key={`${ref.type}-${ref.id}-${index}`} className="chip" onClick={() => ref.type === 'email' && openEmail(ref.id)}>
                      {ref.type} #{ref.id}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {!!agentMeta.tool_trace?.length && (
              <details>
                <summary>工具调用</summary>
                <div className="tool-list">
                  {agentMeta.tool_trace.map((tool, index) => (
                    <div className="tool-item" key={`${tool.tool_name}-${index}`}>
                      <strong>{tool.tool_name}</strong>
                      <span>{tool.preview}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}
        {agentRun && (
          <details className="agent-run" open>
            <summary>Agent Run 日志</summary>
            <pre className="answer">{JSON.stringify(agentRun.events, null, 2)}</pre>
          </details>
        )}
      </section>
    </main>
  );
}

function normalizeEventForEdit(event) {
  return {
    ...event,
    start_time: toLocalInput(event.start_time),
    end_time: toLocalInput(event.end_time),
  };
}

function toIsoFromLocalInput(value) {
  return value ? new Date(value).toISOString() : null;
}

function toLocalInput(value) {
  if (!value) return '';
  const date = new Date(value);
  const offset = date.getTimezoneOffset();
  const local = new Date(date.getTime() - offset * 60000);
  return local.toISOString().slice(0, 16);
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
