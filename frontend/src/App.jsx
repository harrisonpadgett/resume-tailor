import React, { useState } from 'react';
import './App.css';
import { UploadCloud, FileText, ChevronRight, CheckCircle2, RotateCcw, AlertCircle, Loader2, Download, Search } from 'lucide-react';

const API_URL = "http://127.0.0.1:8000/api";

function App() {
  const [sourceData, setSourceData] = useState(null);
  const [resumeTemplate, setResumeTemplate] = useState("");
  const [resumeSource, setResumeSource] = useState(null);
  const [loading, setLoading] = useState(false);
  const [uploadStatusText, setUploadStatusText] = useState("Processing");
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState([]);

  // Tailoring state
  const [jobUrl, setJobUrl] = useState("");
  const [jobText, setJobText] = useState("");
  const [tailorResult, setTailorResult] = useState(null);
  const [activeTab, setActiveTab] = useState("jd");
  const [forceRun, setForceRun] = useState(false);

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setLoading(true);
    setUploadStatusText("Uploading resume...");
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);

      setUploadStatusText("Sending file to extraction pipeline...");
      const res = await fetch(`${API_URL}/extract`, {
        method: "POST",
        body: formData,
      });
      setUploadStatusText("Running LLM extraction on LaTeX content...");
      const data = await res.json();
      setUploadStatusText("Building resume profile from extracted data...");

      if (!res.ok) throw new Error(data.detail || "Extraction failed");
      setSourceData(data.source_data);
      setResumeTemplate(data.resume_template);
      setResumeSource("uploaded");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setUploadStatusText("Processing");
    }
  };

  const handleUseSample = async () => {
    setLoading(true);
    setUploadStatusText("Loading sample resume...");
    setError(null);
    try {
      const res = await fetch(`${API_URL}/sample`);
      setUploadStatusText("Preparing sample source_data and template...");
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed to load sample data");

      setSourceData(data.source_data);
      setResumeTemplate(data.resume_template);
      setResumeSource("sample");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setUploadStatusText("Processing");
    }
  };

  const handleTailor = async () => {
    if (!jobUrl && !jobText) {
      setError("Please provide a Job URL or Description.");
      return;
    }

    setLoading(true);
    setError(null);
    setLogs([]);
    try {
      const res = await fetch(`${API_URL}/tailor`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_target: jobUrl,
          job_text: jobText,
          source_data: sourceData,
          resume_template: resumeTemplate,
          force_run: forceRun
        }),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop(); // keep incomplete chunk

        for (const line of lines) {
          if (!line.trim()) continue;
          const data = JSON.parse(line);
          if (data.error) throw new Error(data.error);
          if (data.log) {
            setLogs(prev => [...prev, data.log]);
          }
          if (data.result) {
            setTailorResult(data.result);
          }
        }
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!tailorResult?.res_tex) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/compile`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tex_content: tailorResult.res_tex }),
      });
      if (!res.ok) throw new Error("Compilation failed");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `Resume_${tailorResult.company?.replace(/ /g, '_') || 'Tailored'}.pdf`;
      a.click();
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const escapeRegExp = (string) => {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); // $& means the whole matched string
  };

  const highlightJD = (text) => {
    if (!tailorResult) return text;
    let newText = text;

    // Sort by length descending to prevent partial replacements
    const allKws = [
      ...tailorResult.found_keywords.map(k => ({ word: k, type: 'found' })),
      ...tailorResult.added_keywords.map(k => ({ word: k, type: 'added' })),
      ...tailorResult.missing_keywords.map(k => ({ word: k, type: 'missing' }))
    ].sort((a, b) => b.word.length - a.word.length);

    allKws.forEach(({ word, type }) => {
      // Safely escape special characters like C++, Node.js, C#
      const escapedWord = escapeRegExp(word);
      const regex = new RegExp(`(?<![a-zA-Z0-9])(${escapedWord})(?![a-zA-Z0-9])`, 'gi');
      newText = newText.replace(regex, `<span class="highlight-${type}">$1</span>`);
    });

    return <div className="jd-container" dangerouslySetInnerHTML={{ __html: newText }} />;
  };

  // Simple word-level inline diff using LCS to create overlapping (inline) diffs
  const escapeHtml = (str) => {
    if (!str && str !== '') return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  };

  const diffWordsToHtml = (oldStr = '', newStr = '') => {
    const a = String(oldStr).split(/(\s+)/).filter(Boolean);
    const b = String(newStr).split(/(\s+)/).filter(Boolean);
    const n = a.length, m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));

    for (let i = 1; i <= n; i++) {
      for (let j = 1; j <= m; j++) {
        if (a[i - 1] === b[j - 1]) dp[i][j] = dp[i - 1][j - 1] + 1;
        else dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }

    const ops = [];
    let i = n, j = m;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
        ops.push({ type: 'common', text: a[i - 1] });
        i--; j--;
      } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
        ops.push({ type: 'insert', text: b[j - 1] });
        j--;
      } else {
        ops.push({ type: 'delete', text: a[i - 1] });
        i--;
      }
    }

    ops.reverse();

    const parts = ops.map(op => {
      const txt = escapeHtml(op.text);
      if (op.type === 'common') return txt;
      if (op.type === 'delete') return `<span class="diff-del">${txt}</span>`;
      return `<span class="diff-ins">${txt}</span>`;
    });

    return parts.join(''); // preserve whitespace tokens from split
  };

  const OutputCard = (
    <div className="card" style={{ minHeight: '600px', display: 'flex', flexDirection: 'column' }}>
      <div className="tabs">
        <div className={`tab ${activeTab === 'jd' ? 'active' : ''}`} onClick={() => setActiveTab('jd')}>Job Description</div>
        <div className={`tab ${activeTab === 'changes' ? 'active' : ''}`} onClick={() => setActiveTab('changes')}>Changes</div>
        <div className={`tab ${activeTab === 'preview' ? 'active' : ''}`} onClick={() => setActiveTab('preview')}>LaTeX Output</div>
      </div>


      {activeTab === 'jd' && (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <div style={{ marginBottom: '1.5rem', padding: '1rem', backgroundColor: '#f8f9fa', border: '1px solid var(--border-color)', borderRadius: '6px' }}>
            <h4 style={{ marginBottom: '0.5rem', fontSize: '0.9rem' }}>Highlight Legend</h4>
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <span className="badge highlight-found">Found Original</span>
              <span className="badge highlight-added">Injected by AI</span>
              <span className="badge highlight-missing">Missing</span>
            </div>
          </div>
          {highlightJD(tailorResult?.jd_content || '')}
        </div>
      )}

      {activeTab === 'changes' && (
        <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '1rem', paddingRight: '0.25rem' }}>
          {[
            ...(tailorResult.res_json?.experience || []).map(exp => ({
              title: exp.role || exp.company || 'Experience',
              bullets: (exp.bullets || []).filter(b => b && (b.original !== b.tailored || b.rationale.includes("REJECTED")))
            })),
            ...(tailorResult.res_json?.projects || []).map(prj => ({
              title: prj.name || 'Project',
              bullets: (prj.bullets || []).filter(b => b && (b.original !== b.tailored || b.rationale.includes("REJECTED")))
            }))
          ].filter(section => section.bullets.length > 0).map((section, sectionIndex) => {
            const rationales = (section.bullets || []).map(b => b.rationale).filter(Boolean);
            const rejectedCount = (section.bullets || []).filter(b => b.rationale && b.rationale.includes('REJECTED')).length;
            const nonRejected = rationales.filter(r => !r.includes('REJECTED'));
            const unique = Array.from(new Set(nonRejected.map(r => r.trim())));
            let sectionSummary = unique.join(' · ');
            if (rejectedCount) sectionSummary = sectionSummary ? `${sectionSummary} · ${rejectedCount} hallucination(s) blocked` : `${rejectedCount} hallucination(s) blocked`;
            if (sectionSummary && sectionSummary.length > 220) sectionSummary = sectionSummary.slice(0, 220) + '...';

            return (
              <div key={sectionIndex} style={{ border: '1px solid var(--border-color)', borderRadius: '6px', backgroundColor: '#fff' }}>
                <div style={{ fontWeight: 600, padding: '0.75rem 1rem', borderBottom: '1px solid var(--border-color)', backgroundColor: '#f8f9fa', color: 'var(--text-main)' }}>
                  {section.title}
                </div>
                {sectionSummary && (
                  <div className="section-rationale" style={{ padding: '0.5rem 1rem', fontSize: '0.9rem', fontStyle: 'italic', color: 'var(--text-muted)' }}>
                    {sectionSummary}
                  </div>
                )}
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {section.bullets.map((b, bulletIndex) => {
                    const isRejected = b.rationale && b.rationale.includes("REJECTED");

                    return (
                      <div key={bulletIndex} style={{ borderBottom: bulletIndex < section.bullets.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                        {isRejected ? (
                          <div style={{ padding: '1rem', fontFamily: 'monospace', fontSize: '0.85rem', backgroundColor: 'var(--danger-bg)', borderLeft: '4px solid var(--danger-text)' }}>
                            <div style={{ fontWeight: 600, marginBottom: '0.5rem', color: 'var(--danger-text)' }}>🛡️ Hallucination Blocked</div>
                            <span style={{ color: 'var(--text-main)' }}>{b.original}</span>
                          </div>
                        ) : (
                          <div className="diff-container" style={{ padding: '0.5rem 1rem', fontFamily: 'monospace', fontSize: '0.85rem' }} dangerouslySetInnerHTML={{ __html: diffWordsToHtml(b.original, b.tailored) }} />
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {activeTab === 'preview' && (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <h3 style={{ fontSize: '1rem' }}>Ready to compile!</h3>
            <button className="btn btn-primary" onClick={handleDownload} disabled={loading}>
              {loading ? <Loader2 className="lucide-spin" /> : <Download size={18} />} Download PDF
            </button>
          </div>
          <textarea
            className="input-field"
            style={{ flex: 1, fontFamily: 'monospace', fontSize: '0.85rem' }}
            readOnly
            value={tailorResult.res_tex}
          />
        </div>
      )}
    </div>
  );

  // Show logs in the input column (below Upload Job). When keywords exist,
  // the Keywords card renders first and LogsCard will appear below it.
  const showLogs = loading || logs.length > 0;

  const LogsCard = (
    <div className="card">
      <h2 className="card-title">Logs</h2>
      <div style={{ padding: '0.75rem', backgroundColor: '#000000', color: '#00ff66', fontFamily: 'monospace', fontSize: '0.85rem', borderRadius: '6px', maxHeight: '220px', overflowY: 'auto' }}>
        {logs.map((log, i) => (
          <div key={i} style={{ marginBottom: '4px' }}>&gt; {log}</div>
        ))}
        {loading && <div className="cursor-blink" style={{ display: 'inline-block', width: '8px', height: '14px', backgroundColor: '#00ff66', marginTop: '4px' }}></div>}
      </div>
    </div>
  );

  if (!sourceData) {
    return (
      <div className="dashboard-container">
        <header className="topbar">
          <div className="topbar-logo"><FileText /> Resume Tailor</div>
        </header>
        <main className="main-content" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
          <div className="card" style={{ maxWidth: '600px', width: '100%' }}>
            <h2 className="card-title">Upload Your Resume</h2>
            <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>Upload your existing LaTeX (.tex) resume, or use the provided sample resume if you just want to test out the project.</p>

            {error && <div className="alert alert-danger">{error}</div>}

            <div className="grid-2" style={{ gap: '1rem' }}>
              <label className="file-drop">
                <UploadCloud size={48} color="var(--primary)" style={{ margin: '0 auto 1rem' }} />
                <div style={{ fontWeight: 500, fontSize: '1.1rem' }}>Click to upload .tex file</div>
                <input type="file" accept=".tex" style={{ display: 'none' }} onChange={handleFileUpload} disabled={loading} />
              </label>

              <div className="file-drop" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', backgroundColor: 'var(--bg-card)' }} onClick={handleUseSample}>
                <FileText size={48} color="var(--text-muted)" style={{ margin: '0 auto 1rem' }} />
                <div style={{ fontWeight: 500, fontSize: '1.1rem' }}>Use Sample Resume</div>
                <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '0.5rem' }}>Test the pipeline without a file</div>
              </div>
            </div>

            {loading && (
              <div style={{ textAlign: 'center', marginTop: '1rem' }}>
                <span className="loader-inline"><Loader2 className="lucide-spin" /> <span>{uploadStatusText}</span></span>
              </div>
            )}
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="dashboard-container">
      <header className="topbar">
        <div className="topbar-logo"><FileText /> Resume Tailor</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <span className="badge" style={{ backgroundColor: 'var(--success-bg)', color: 'var(--success-text)', marginBottom: 0 }}>
            {resumeSource === "uploaded" ? "Uploaded Resume Active" : "Sample Resume Active"}
          </span>
          <button className="btn btn-outline" style={{ padding: '0.4rem 1rem' }} onClick={() => { setSourceData(null); setTailorResult(null); setResumeSource(null); }}>
            <RotateCcw size={16} /> Start Over
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="grid-2">
          {/* Input Side */}
          <div>
            <div className="card">
              <h2 className="card-title">Upload Job</h2>
              <div className="input-group">
                <label className="input-label">Job URL</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="https://linkedin.com/jobs/view/..."
                  value={jobUrl}
                  onChange={(e) => setJobUrl(e.target.value)}
                />
              </div>

              <div style={{ textAlign: 'center', margin: '1rem 0', color: 'var(--text-muted)' }}>OR</div>

              <div className="input-group">
                <label className="input-label">Paste Job Description</label>
                <textarea
                  className="input-field"
                  style={{ height: '150px', resize: 'vertical' }}
                  placeholder="We are looking for a software engineer with experience in..."
                  value={jobText}
                  onChange={(e) => setJobText(e.target.value)}
                />
              </div>

              <div style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <input
                  type="checkbox"
                  id="force-run-checkbox"
                  checked={forceRun}
                  onChange={(e) => setForceRun(e.target.checked)}
                  style={{ width: '16px', height: '16px', cursor: 'pointer' }}
                />
                <label htmlFor="force-run-checkbox" style={{ fontSize: '0.9rem', cursor: 'pointer', color: 'var(--text-main)' }}>
                  Force Rerun (Bypass Cache)
                </label>
              </div>

              <button className="btn btn-primary btn-block" onClick={handleTailor} disabled={loading}>
                {loading ? <><Loader2 className="lucide-spin" /> Processing</> : "Tailor Resume"}
              </button>

              {error && <div className="alert alert-danger" style={{ marginTop: '1rem' }}>{error}</div>}

              {/* Logs are consolidated into a single Logs card (rendered elsewhere) */}
            </div>

            {tailorResult && (
              <div className="card">
                <h2 className="card-title">Keywords</h2>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1rem' }}>
                  <div className="metric-box">
                    <div className="metric-value">{tailorResult.target_keywords.length}</div>
                    <div className="metric-label" style={{ fontSize: '0.75rem' }}>Total Target</div>
                  </div>
                  <div className="metric-box">
                    <div className="metric-value">{tailorResult.found_keywords.length}</div>
                    <div className="metric-label" style={{ fontSize: '0.75rem' }}>Original</div>
                  </div>
                  <div className="metric-box" style={{ borderColor: 'var(--success-text)' }}>
                    <div className="metric-value" style={{ color: 'var(--success-text)' }}>+{tailorResult.added_keywords.length}</div>
                    <div className="metric-label" style={{ fontSize: '0.75rem' }}>Injected</div>
                  </div>
                  <div className="metric-box" style={{ borderColor: 'var(--danger-text)' }}>
                    <div className="metric-value" style={{ color: 'var(--danger-text)' }}>{tailorResult.missing_keywords.length}</div>
                    <div className="metric-label" style={{ fontSize: '0.75rem' }}>Missing</div>
                  </div>
                </div>

              </div>
            )}
            {showLogs && LogsCard}
          </div>

          {/* Output Side */}
          <div>
            {tailorResult ? (
              OutputCard
            ) : (
              <div className="card" style={{ minHeight: '600px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                <div style={{ textAlign: 'center' }}>
                  <Search size={48} style={{ margin: '0 auto 1rem', opacity: 0.5 }} />
                  <p>Provide a job description to see your tailored results.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
