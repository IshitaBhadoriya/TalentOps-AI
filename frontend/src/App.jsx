import React, { useEffect, useState, useCallback } from "react";

const STATUSES = ["Pending Review", "Shortlisted", "Further Review Required"];

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, opts);
  let body = null;
  try { body = await res.json(); } catch { /* empty */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : "Request failed (" + res.status + ")");
  }
  return body;
}
const post = (p, data) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
const fmt = (v) => (v === null || v === undefined ? "-" : v);

function Msg({ kind = "info", children }) { return children ? <div className={"msg " + kind}>{children}</div> : null; }

function Dashboard({ go, refreshKey, onDemo }) {
  const [m, setM] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { api("/metrics").then(setM).catch((e) => setErr(e.message)); }, [refreshKey]);
  if (err) return <Msg kind="err">{err}</Msg>;
  if (!m) return <p>Loading...</p>;
  const cards = [
    ["Candidates processed", m.candidates_processed], ["Screenings run", m.screenings_run],
    ["Pending review", m.pending_review], ["Shortlisted", m.shortlisted],
    ["Further review required", m.further_review_required],
    ["% screenings meeting all required skills", m.pct_meeting_all_required === null ? "-" : m.pct_meeting_all_required + "%"],
  ];
  return (<>
    {m.candidates_processed === 0 && <div className="card"><h2>Welcome</h2>
      <p>No data yet. Load the synthetic demo data (fictional candidates, no real personal information) or upload a resume.</p>
      <button className="primary" onClick={onDemo}>Load synthetic demo data</button></div>}
    <div className="grid">{cards.map(([l, v]) => <div className="card metric" key={l}><b>{v}</b><span>{l}</span></div>)}</div>
    <div className="card"><h2>Pipeline stages</h2>
      <table><tbody>{Object.entries(m.stage_counts).map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody></table></div>
    <div className="card"><h2>Recent workflow events</h2><EventTable events={m.recent_events} /></div>
    <div className="card"><h2>Metric definitions</h2>
      {Object.entries(m.definitions).map(([k, v]) => <p key={k} className="muted"><b>{k}:</b> {v}</p>)}
      <p className="muted">These are counts from this local database. No productivity or business-impact claims are made.</p></div>
  </>);
}

function EventTable({ events }) {
  if (!events.length) return <p className="muted">No events yet.</p>;
  return <table><thead><tr><th>Time (UTC)</th><th>Event</th><th>Cand.</th><th>Job</th><th>Status</th><th>n8n delivery</th></tr></thead>
    <tbody>{events.map((e) => <tr key={e.id}><td>{e.created_at.replace("T", " ").slice(0, 19)}</td><td>{e.event_type}<div className="muted">{e.detail}</div></td>
      <td>{fmt(e.candidate_id)}</td><td>{fmt(e.job_id)}</td><td>{fmt(e.status)}</td><td>{e.delivery_status}</td></tr>)}</tbody></table>;
}

function Upload({ onDone, openCandidate }) {
  const [file, setFile] = useState(null);
  const [res, setRes] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setErr(""); setRes(null); setBusy(true);
    try {
      const fd = new FormData(); fd.append("file", file);
      setRes(await api("/candidates/upload", { method: "POST", body: fd })); onDone();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  const p = res && res.profile;
  return (<div className="card"><h2>Upload resume (PDF or DOCX)</h2>
    <p className="muted">Max 5 MB. Scanned/image-only PDFs are not supported (no OCR in this MVP). Files are parsed as data only and are not stored on disk.</p>
    <div className="row"><input type="file" accept=".pdf,.docx" onChange={(e) => setFile(e.target.files[0])} style={{ width: "auto" }} />
      <button className="primary" disabled={!file || busy} onClick={submit}>{busy ? "Processing..." : "Upload & parse"}</button></div>
    <Msg kind="err">{err}</Msg>
    {res && <>
      <Msg kind={res.duplicate ? "warn" : "info"}>{res.message}</Msg>
      {res.possible_duplicates.map((d) => <Msg kind="warn" key={d.id}>Possible duplicate: candidate #{d.id} ({d.name || "unnamed"}) - {d.reason}. Not merged.</Msg>)}
      <button className="ghost" onClick={() => openCandidate(res.candidate_id)}>Open candidate #{res.candidate_id}</button>
      <ProfileView profile={p} />
      <h3>Extracted text preview</h3><pre>{res.text_preview}</pre></>}
  </div>);
}

function ProfileView({ profile: p }) {
  const list = (t, a) => a && a.length > 0 && <><h3>{t}</h3><ul>{a.map((x, i) => <li key={i}>{x}</li>)}</ul></>;
  return (<div>
    <h3>Structured profile</h3>
    <p><b>Name:</b> {p.name || "not detected"} {p.name_confidence === "uncertain" && <span className="badge">uncertain</span>}
      {" "}<b>Email:</b> {p.email || "not found"} {" "}<b>Phone:</b> {p.phone || "not found"}
      {" "}<b>Declared experience:</b> {p.declared_years_experience ?? "not stated"}{p.declared_years_experience != null && " yrs (unverified)"}</p>
    {p.skills.length > 0 && <><h3>Skills</h3><div className="tags">{p.skills.map((s) => <span key={s}>{s}</span>)}</div></>}
    {list("Education", p.education)}{list("Work experience", p.experience)}{list("Projects", p.projects)}{list("Certifications", p.certifications)}
    {p.warnings.length > 0 && <Msg kind="warn"><b>Parsing warnings / missing information</b><ul>{p.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></Msg>}
  </div>);
}

function Jobs({ onDone }) {
  const [jobs, setJobs] = useState([]);
  const [f, setF] = useState({ title: "", description: "", req: "", pref: "", min: "" });
  const [err, setErr] = useState("");
  const load = useCallback(() => api("/jobs").then(setJobs), []);
  useEffect(() => { load(); }, [load]);
  const split = (s) => s.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
  async function save() {
    setErr("");
    try {
      await post("/jobs", { title: f.title, description: f.description, required_skills: split(f.req), preferred_skills: split(f.pref),
        min_experience_years: f.min === "" ? null : Number(f.min) });
      setF({ title: "", description: "", req: "", pref: "", min: "" }); load(); onDone();
    } catch (e) { setErr(e.message); }
  }
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (<>
    <div className="card"><h2>Create job description</h2>
      <label>Job title</label><input value={f.title} onChange={set("title")} />
      <label>Description</label><textarea rows="4" value={f.description} onChange={set("description")} />
      <label>Required skills (comma separated)</label><input value={f.req} onChange={set("req")} placeholder="Python, SQL, REST APIs" />
      <label>Preferred skills (comma separated)</label><input value={f.pref} onChange={set("pref")} placeholder="NLP, Docker" />
      <label>Minimum experience in years (optional)</label><input type="number" min="0" value={f.min} onChange={set("min")} />
      <Msg kind="err">{err}</Msg><button className="primary" onClick={save}>Save job</button></div>
    <div className="card"><h2>Jobs</h2>{jobs.length === 0 ? <p className="muted">No jobs yet.</p> :
      <table><thead><tr><th>ID</th><th>Title</th><th>Required</th><th>Preferred</th><th>Min exp</th></tr></thead>
        <tbody>{jobs.map((j) => <tr key={j.id}><td>{j.id}</td><td>{j.title}</td><td>{j.required_skills.join(", ")}</td><td>{j.preferred_skills.join(", ")}</td><td>{fmt(j.min_experience_years)}</td></tr>)}</tbody></table>}</div>
  </>);
}

function Candidates({ openCandidate, refreshKey }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState([]);
  useEffect(() => { api("/candidates?q=" + encodeURIComponent(q)).then(setRows); }, [q, refreshKey]);
  return (<div className="card"><h2>Candidates</h2>
    <input placeholder="Search by name, email or skill..." value={q} onChange={(e) => setQ(e.target.value)} />
    {rows.length === 0 ? <p className="muted">No candidates found.</p> :
      <table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Skills</th><th>Stage</th><th>Latest score</th></tr></thead>
        <tbody>{rows.map((r) => <tr className="click" key={r.id} onClick={() => openCandidate(r.id)}>
          <td>{r.id}</td><td>{r.name || "(unnamed)"} {r.is_synthetic && <span className="badge">synthetic</span>}</td><td>{r.email || "-"}</td>
          <td>{r.skills.slice(0, 5).join(", ")}</td><td><span className="badge">{r.stage}</span></td><td>{fmt(r.latest_score)}</td></tr>)}</tbody></table>}
  </div>);
}

function Ranking({ openCandidate, refreshKey, onDone }) {
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/jobs").then((j) => { setJobs(j); if (j[0] && !jobId) setJobId(String(j[0].id)); }); }, [refreshKey]);
  const load = useCallback(() => (jobId ? api("/jobs/" + jobId + "/ranking").then(setData).catch((e) => setMsg(e.message)) : null), [jobId]);
  useEffect(() => { load(); }, [load, refreshKey]);
  async function screenAll() {
    setBusy(true); setMsg("");
    try { const o = await api("/jobs/" + jobId + "/screen-all", { method: "POST" }); setMsg("Screened " + o.newly_screened + " new candidate(s)."); await load(); onDone(); }
    catch (e) { setMsg(e.message); } finally { setBusy(false); }
  }
  return (<div className="card"><h2>Candidate ranking by job</h2>
    {jobs.length === 0 ? <p className="muted">Create a job first.</p> : <>
      <div className="row"><select style={{ width: 320, margin: 0 }} value={jobId} onChange={(e) => setJobId(e.target.value)}>{jobs.map((j) => <option key={j.id} value={j.id}>#{j.id} {j.title}</option>)}</select>
        <button className="primary" disabled={busy || !jobId} onClick={screenAll}>{busy ? "Screening..." : "Screen all unscreened candidates"}</button>
        {jobId && <a href={"/api/jobs/" + jobId + "/ranking.csv"}><button className="ghost">Download CSV</button></a>}</div>
      {msg && <Msg>{msg}</Msg>}
      {data && <><Msg kind="warn">{data.note}</Msg>
        {data.items.length === 0 ? <p className="muted">No screenings for this job yet.</p> :
          <table><thead><tr><th>Rank</th><th>Candidate</th><th>Coverage score</th><th>Matched / partial / insufficient</th><th>Required skills without evidence</th><th>Review status</th></tr></thead>
            <tbody>{data.items.map((i) => <tr className="click" key={i.screening_id} onClick={() => openCandidate(i.candidate_id)}>
              <td>{fmt(i.rank)}</td><td>{i.name || "#" + i.candidate_id} {i.is_synthetic && <span className="badge">synthetic</span>}</td><td>{fmt(i.score)}</td>
              <td>{i.counts.matched} / {i.counts.partial} / {i.counts.insufficient}</td><td>{i.missing_required.join(", ") || "-"}</td><td><span className="badge">{i.review_status}</span></td></tr>)}</tbody></table>}</>}</>}
  </div>);
}

function ScreeningView({ s, reload }) {
  const r = s.result;
  const [msg, setMsg] = useState("");
  async function setStatus(status) {
    try { const o = await api("/screenings/" + s.id + "/status", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
      setMsg("Status set. n8n delivery: " + o.delivery); reload(); } catch (e) { setMsg(e.message); }
  }
  return (<div className="card">
    <h2>Screening #{s.id} - {s.job_title}</h2>
    <p className="muted">{s.created_at.replace("T", " ")} UTC | backend: {r.backend}</p>
    <div className="row"><b>Coverage score: {fmt(r.score)}</b>{r.score !== null && <div className="bar" style={{ width: 200 }}><i style={{ width: r.score + "%" }} /></div>}
      <span className="muted">required coverage {r.required_coverage === null ? "-" : Math.round(r.required_coverage * 100) + "%"} | preferred {r.preferred_coverage === null ? "-" : Math.round(r.preferred_coverage * 100) + "%"}</span></div>
    <Msg kind="info"><b>How this is calculated:</b> {r.score_explanation}</Msg>
    <table><thead><tr><th>Requirement</th><th>Result</th><th>Supporting resume text</th></tr></thead><tbody>
      {r.requirements.map((q) => <tr key={q.requirement + q.type}>
        <td>{q.requirement}<div className="muted">{q.type}</div></td>
        <td><span className={"badge " + q.status}>{q.status === "insufficient" ? "insufficient evidence" : q.status}</span><div className="muted">{q.match_type !== "none" && q.match_type + " / sim " + q.similarity}</div></td>
        <td>{q.evidence.length ? q.evidence.map((e, i) => <div className="evidence" key={i}>{e}</div>) : <span className="muted">No supporting text found (this does not prove the candidate lacks the skill).</span>}
          {(q.excluded_evidence || []).map((e, i) => <div className="evidence" style={{ opacity: 0.7, borderColor: "#e67700" }} key={"x" + i}>Excluded (mentioned only as a goal, plan or negation - please verify): {e}</div>)}</td></tr>)}
    </tbody></table>
    <p className="muted">Experience: {r.experience_check.status} - {r.experience_check.note} {r.description_similarity !== null && " | Whole-description similarity (context only): " + r.description_similarity}</p>
    <Msg kind="warn">{r.disclaimer}</Msg>
    <div className="row"><b>Human review status:</b> {STATUSES.map((st) => <button key={st} className="ghost" disabled={s.review_status === st}
      style={s.review_status === st ? { background: "#dbe4ff" } : {}} onClick={() => setStatus(st)}>{st}</button>)}</div>
    {msg && <Msg>{msg}</Msg>}
  </div>);
}

function CandidateDetail({ id, onChange }) {
  const [c, setC] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api("/candidates/" + id).then(setC), [id]);
  useEffect(() => { load(); api("/jobs").then((j) => { setJobs(j); if (j[0]) setJobId(String(j[0].id)); }); }, [load]);
  async function screen() {
    setErr(""); setBusy(true);
    try { await post("/screenings", { candidate_id: id, job_id: Number(jobId) }); await load(); onChange(); }
    catch (e) { setErr(e.message); } finally { setBusy(false); }
  }
  if (!c) return <p>Loading...</p>;
  return (<>
    <div className="card"><h2>Candidate #{c.id} {c.is_synthetic && <span className="badge">synthetic</span>}</h2>
      <p className="muted">Source: {c.source_filename || "-"} | added {c.created_at.replace("T", " ")} UTC</p>
      <ProfileView profile={c.profile} /><h3>Resume text (preview)</h3><pre>{c.text_preview}</pre></div>
    <div className="card"><h2>Screen against a job</h2>
      {jobs.length === 0 ? <p className="muted">Create a job first.</p> : <div className="row">
        <select style={{ width: 320, margin: 0 }} value={jobId} onChange={(e) => setJobId(e.target.value)}>{jobs.map((j) => <option key={j.id} value={j.id}>#{j.id} {j.title}</option>)}</select>
        <button className="primary" disabled={busy} onClick={screen}>{busy ? "Matching (first run may load the model)..." : "Run screening"}</button></div>}
      <Msg kind="err">{err}</Msg></div>
    <h2>Screening history</h2>
    {c.screenings.length === 0 ? <p className="muted">No screenings yet.</p> : c.screenings.map((s) => <ScreeningView key={s.id} s={s} reload={() => { load(); onChange(); }} />)}
    <div className="card"><h2>Workflow event history</h2><EventTable events={c.events} /></div>
  </>);
}

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [cid, setCid] = useState(null);
  const [key, setKey] = useState(0);
  const bump = () => setKey((k) => k + 1);
  const openCandidate = (id) => { setCid(id); setTab("detail"); };
  async function demo() { await api("/demo/load", { method: "POST" }); bump(); }
  const tabs = [["dashboard", "Dashboard"], ["upload", "Upload resume"], ["jobs", "Jobs"], ["candidates", "Candidates"], ["ranking", "Ranking"]];
  return (<>
    <header><div><h1>TalentOps AI</h1><small>Evidence-based recruitment intelligence - human review required</small></div>
      <nav>{tabs.map(([k, l]) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}</nav></header>
    <main>
      {tab === "dashboard" && <Dashboard refreshKey={key} onDemo={demo} />}
      {tab === "upload" && <Upload onDone={bump} openCandidate={openCandidate} />}
      {tab === "jobs" && <Jobs onDone={bump} />}
      {tab === "candidates" && <Candidates openCandidate={openCandidate} refreshKey={key} />}
      {tab === "ranking" && <Ranking openCandidate={openCandidate} refreshKey={key} onDone={bump} />}
      {tab === "detail" && cid && <><button className="ghost" onClick={() => setTab("candidates")}>Back to list</button><CandidateDetail id={cid} onChange={bump} /></>}
    </main></>);
}
