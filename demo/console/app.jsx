const { useState, useEffect, useRef } = React;

function App() {
  const [activeTab, setActiveTab] = useState("live");
  const [status, setStatus] = useState({
    gemma_backend: "loading...",
    model_name: "checking...",
    reachable: false,
    strict_mode: false,
    demo_mode: true,
    upstream_host: "--",
    simulated_gemma_down: false
  });

  const [inputPrompt, setInputPrompt] = useState("");
  const [activePreset, setActivePreset] = useState("loan");
  
  // Toggles
  const [proxyEnabled, setProxyEnabled] = useState(true);
  const [gemmaLayer, setGemmaLayer] = useState(true);
  const [strictMode, setStrictMode] = useState(false);
  const [streamingSse, setStreamingSse] = useState(true);

  // Execution outputs
  const [isExecuting, setIsExecuting] = useState(false);
  const [spans, setSpans] = useState([]);
  const [cloudSaw, setCloudSaw] = useState("Click 'Execute Proxy Request' to run test...");
  const [restoredReply, setRestoredReply] = useState("Awaiting execution...");
  const [receipt, setReceipt] = useState({});
  const [timings, setTimings] = useState({ rules: 0, gemma: 0, upstream: 0, restore: 0 });
  const [errorMessage, setErrorMessage] = useState(null);

  // Gemma Impact State
  const [gemmaImpact, setGemmaImpact] = useState({ rules: null, combo: null, loading: false });

  // Compare State
  const [compareData, setCompareData] = useState({ raw: null, masked: null, loading: false });

  // Stream Trace State
  const [traceRows, setTraceRows] = useState([]);
  const [isTracing, setIsTracing] = useState(false);

  // Failure Test State
  const [failResult, setFailResult] = useState({ nonStrict: null, strict: null });

  // Benchmark State
  const [benchmark, setBenchmark] = useState({ metrics: null, loading: false });

  // Verhoeff algorithm for dynamic Aadhaar generation
  const generateDynamicAadhaar = () => {
    const d_table = [
      [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
      [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
      [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
      [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
    ];
    const p_table = [
      [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
      [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
      [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
    ];
    const inv_table = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9];
    const prefix = "36759834120";
    let c = 0;
    const rev = prefix.split("").reverse();
    for (let i = 0; i < rev.length; i++) {
      c = d_table[c][p_table[(i + 1) % 8][parseInt(rev[i])]];
    }
    return prefix + inv_table[c];
  };

  const presets = {
    loan: `Hello, I am applying for a personal loan. My name is Rajesh Sharma, residing at Flat 402, Green Glen Layout, Bellandur, Bengaluru. My Aadhaar is ${generateDynamicAadhaar()}, PAN is ABCPB1234F, and mobile is 9876543210. Pay processing fee to rajesh@oksbi.`,
    hinglish: `Bhai Vikram ko bolo 9876543210 pe call kare. Uska PAN number XYZPH9876K and Aadhaar ${generateDynamicAadhaar()} verify karna hai.`,
    devops: `[ERROR] Production deploy failed! AWS key AKIAIOSFODNN7EXAMPLE leaked in log file. GitHub PAT token: github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz. Admin email: devsec@company.in`,
    negatives: `Order ID 123456789012 was processed. Invalid check number 367598341209 and bad PAN ABCXX1234F should be ignored. Product code SBIN1001234 is not IFSC.`,
    bengali: `আমার আধার নম্বর ৩৬৭৫৯৮৩৪১২০৩ এবং মোবাইল ৯৮৭৬৫৪৩২১০।`
  };

  // Poll status
  const fetchStatus = async () => {
    try {
      const res = await fetch("/demo/status");
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (e) {}
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    loadPresetKey("loan");
    return () => clearInterval(interval);
  }, []);

  const loadPresetKey = (key) => {
    setActivePreset(key);
    const text = presets[key] || "";
    setInputPrompt(text);
    analyzeText(text, gemmaLayer);
  };

  const analyzeText = async (text, useGemma) => {
    if (!text.trim()) {
      setSpans([]);
      return;
    }
    try {
      const res = await fetch("/demo/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, use_gemma: useGemma })
      });
      if (res.ok) {
        const data = await res.json();
        setSpans(data.spans || []);
      }
    } catch (e) {}
  };

  const handleInputChange = (e) => {
    const val = e.target.value;
    setInputPrompt(val);
    analyzeText(val, gemmaLayer);
  };

  const handleGemmaToggle = (e) => {
    const checked = e.target.checked;
    setGemmaLayer(checked);
    analyzeText(inputPrompt, checked);
  };

  const executeRequest = async () => {
    setIsExecuting(true);
    setErrorMessage(null);
    setCloudSaw("Encrypting PII and generating token placeholders...");
    setRestoredReply("Waiting for upstream LLM response...");

    try {
      const res = await fetch("/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: inputPrompt,
          proxy: proxyEnabled,
          use_gemma: gemmaLayer,
          strict: strictMode,
          stream: streamingSse
        })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: res.statusText }));
        setErrorMessage(`HTTP ${res.status}: ${errData.detail || "Proxy Error"}`);
        setCloudSaw("Request stopped due to error.");
        setRestoredReply(`HTTP ${res.status} Error: ${errData.detail}`);
        return;
      }

      const data = await res.json();
      setCloudSaw(data.cloud_saw);
      setRestoredReply(data.restored_reply);
      setReceipt(data.receipt || {});
      setTimings(data.timings_ms || { rules: 0, gemma: 0, upstream: 0, restore: 0 });
    } catch (e) {
      setErrorMessage(`Network error: ${e.message}`);
    } finally {
      setIsExecuting(false);
    }
  };

  // Gemma Impact Analysis
  const runGemmaImpact = async () => {
    setGemmaImpact({ rules: null, combo: null, loading: true });
    try {
      const resRules = await fetch("/demo/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt, use_gemma: false })
      });
      const rulesData = await resRules.json();

      const resCombo = await fetch("/demo/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt, use_gemma: true })
      });
      const comboData = await resCombo.json();

      setGemmaImpact({ rules: rulesData.spans, combo: comboData.spans, loading: false });
    } catch (e) {
      setGemmaImpact({ rules: [], combo: [], loading: false });
    }
  };

  // Compare Test
  const runCompareTest = async () => {
    setCompareData({ raw: null, masked: null, loading: true });
    try {
      const resRaw = await fetch("/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt, proxy: false, stream: false })
      });
      const rawJson = await resRaw.json();

      const resMasked = await fetch("/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt, proxy: true, stream: false })
      });
      const maskedJson = await resMasked.json();

      setCompareData({ raw: rawJson.cloud_saw, masked: maskedJson.cloud_saw, loading: false });
    } catch (e) {
      setCompareData({ raw: "Error", masked: "Error", loading: false });
    }
  };

  // Stream Trace
  const runStreamTrace = async () => {
    setIsTracing(true);
    setTraceRows([]);
    try {
      const res = await fetch("/demo/stream-trace", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt })
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let step = 1;
      const rows = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const str = decoder.decode(value);
        const lines = str.split("\n");
        for (let line of lines) {
          line = line.trim();
          if (!line.startsWith("data: ")) continue;
          const payload = line.substring(6).trim();
          if (payload === "[DONE]") break;

          try {
            const item = JSON.parse(payload);
            rows.push({
              step: step++,
              chunk: item.upstream_chunk,
              buffer: item.held_buffer,
              emitted: item.emitted
            });
            setTraceRows([...rows]);
          } catch (err) {}
        }
      }
    } catch (e) {} finally {
      setIsTracing(false);
    }
  };

  // Failure Simulation
  const simulateGemma = async (mode) => {
    try {
      const res = await fetch("/demo/simulate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode })
      });
      fetchStatus();
    } catch (e) {}
  };

  const runFailureTest = async (strict) => {
    try {
      const res = await fetch("/demo/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: inputPrompt, proxy: true, use_gemma: true, strict })
      });
      const data = await res.json().catch(() => ({ detail: res.statusText }));
      if (strict) {
        setFailResult(prev => ({ ...prev, strict: JSON.stringify(data, null, 2) }));
      } else {
        setFailResult(prev => ({ ...prev, nonStrict: JSON.stringify(data, null, 2) }));
      }
    } catch (e) {
      if (strict) {
        setFailResult(prev => ({ ...prev, strict: `Error: ${e.message}` }));
      } else {
        setFailResult(prev => ({ ...prev, nonStrict: `Error: ${e.message}` }));
      }
    }
  };

  // Load Benchmark
  const fetchBenchmark = async () => {
    setBenchmark({ metrics: null, loading: true });
    try {
      const res = await fetch("/demo/benchmark");
      const data = await res.json();
      setBenchmark({ metrics: data.metrics || null, loading: false });
    } catch (e) {
      setBenchmark({ metrics: null, loading: false });
    }
  };

  // Render Highlighted Text Spans
  const renderSpanContainer = () => {
    if (!inputPrompt.trim()) return <div className="text-muted">Type prompt above to analyze spans...</div>;
    if (!spans || spans.length === 0) return <div>{inputPrompt}</div>;

    const elements = [];
    let lastIdx = 0;

    spans.forEach((span, i) => {
      elements.push(inputPrompt.substring(lastIdx, span.start));
      const entityText = inputPrompt.substring(span.start, span.end);
      const isRule = span.source === "rule";
      const tagClass = `tag-${span.type}`;

      elements.push(
        <span key={i} className={`span-tag ${tagClass}`} title={`Score: ${span.score} | Source: ${span.source}`}>
          {entityText}
          <span className={`src-badge ${isRule ? "src-rule" : "src-gemma"}`}>{span.source.toUpperCase()}</span>
          {span.type === "AADHAAR" && (
            <span className="verhoeff-tag">{span.checksum_valid ? "✓ Verhoeff" : "✕ Invalid"}</span>
          )}
        </span>
      );
      lastIdx = span.end;
    });

    elements.push(inputPrompt.substring(lastIdx));
    return elements;
  };

  // Render Cloud Saw text with token highlighting
  const renderCloudSawText = () => {
    if (typeof cloudSaw !== "string") return JSON.stringify(cloudSaw, null, 2);

    const parts = cloudSaw.split(/(\[[A-Z_]+_\d+\])/g);
    return parts.map((part, i) => {
      if (/^\[[A-Z_]+_\d+\]$/.test(part)) {
        return <span key={i} className="cloud-token-highlight">{part}</span>;
      }
      return part;
    });
  };

  return (
    <div className="console-container">
      
      <!-- Top Navigation Header -->
      <header className="header">
        <div className="brand-group">
          <div className="brand-logo">🛡️</div>
          <div>
            <div className="brand-title">
              <h1>VaultProxy <span className="gradient-text">Judge Console</span></h1>
              <span className="version-badge">v0.1-core</span>
            </div>
            <p className="brand-subtitle">Zero-Trust Indian PII & Secret Redaction Engine for Cloud LLMs</p>
          </div>
        </div>

        <!-- Telemetry Status Chips -->
        <div className="status-chips">
          <div className={`chip ${status.reachable ? "active-green" : "active-red"}`}>
            <span className="chip-dot"></span>
            Gemma SLM: {status.model_name} {status.reachable ? "(Ready)" : "(Offline)"}
          </div>
          <div className="chip">
            <span className="chip-dot"></span>Strict: {status.strict_mode ? "ON" : "OFF"}
          </div>
          <div className="chip">
            <span className="chip-dot"></span>Upstream: {status.upstream_host}
          </div>
        </div>
      </header>

      <!-- Main Navigation Tabs -->
      <nav className="nav-tabs">
        <button className={`nav-tab ${activeTab === "live" ? "active" : ""}`} onClick={() => setActiveTab("live")}>
          ⚡ Live Proxy Demo
        </button>
        <button className={`nav-tab ${activeTab === "gemma" ? "active" : ""}`} onClick={() => setActiveTab("gemma")}>
          🧠 Gemma SLM Intelligence
        </button>
        <button className={`nav-tab ${activeTab === "compare" ? "active" : ""}`} onClick={() => setActiveTab("compare")}>
          🔒 Cloud Leak Comparison
        </button>
        <button className={`nav-tab ${activeTab === "streaming" ? "active" : ""}`} onClick={() => setActiveTab("streaming")}>
          🌊 Stream Restorer Trace
        </button>
        <button className={`nav-tab ${activeTab === "failure" ? "active" : ""}`} onClick={() => setActiveTab("failure")}>
          🛡️ Fail-Closed Safety
        </button>
        <button className={`nav-tab ${activeTab === "benchmark" ? "active" : ""}`} onClick={() => { setActiveTab("benchmark"); fetchBenchmark(); }}>
          📊 Benchmark Suite
        </button>
      </nav>

      {/* TAB 1: LIVE PROXY */}
      {activeTab === "live" && (
        <main className="tab-content active">
          
          {/* Preset Buttons */}
          <div className="preset-strip">
            <span className="preset-heading">Demo Scenarios:</span>
            <div className="preset-buttons">
              <button className={`preset-btn ${activePreset === "loan" ? "active" : ""}`} onClick={() => loadPresetKey("loan")}>
                💳 1. Loan PII
              </button>
              <button className={`preset-btn ${activePreset === "hinglish" ? "active" : ""}`} onClick={() => loadPresetKey("hinglish")}>
                💬 2. Hinglish Chat
              </button>
              <button className={`preset-btn ${activePreset === "devops" ? "active" : ""}`} onClick={() => loadPresetKey("devops")}>
                🔑 3. DevOps Secrets
              </button>
              <button className={`preset-btn ${activePreset === "negatives" ? "active" : ""}`} onClick={() => loadPresetKey("negatives")}>
                🎯 4. Tricky Negatives
              </button>
              <button className={`preset-btn ${activePreset === "bengali" ? "active" : ""}`} onClick={() => loadPresetKey("bengali")}>
                🇮🇳 5. Indic Bengali Digits
              </button>
            </div>
          </div>

          {/* Controls Toolbar */}
          <div className="toolbar">
            <div className="switches-group">
              <label className="switch-label">
                <span className="switch-title">VaultProxy Active</span>
                <input type="checkbox" checked={proxyEnabled} onChange={e => setProxyEnabled(e.target.checked)} className="custom-switch" />
              </label>

              <label className="switch-label">
                <span className="switch-title">Gemma SLM Layer</span>
                <input type="checkbox" checked={gemmaLayer} onChange={handleGemmaToggle} className="custom-switch" />
              </label>

              <label className="switch-label">
                <span className="switch-title">Strict Mode (Fail-Closed)</span>
                <input type="checkbox" checked={strictMode} onChange={e => setStrictMode(e.target.checked)} className="custom-switch" />
              </label>

              <label className="switch-label">
                <span className="switch-title">Streaming SSE</span>
                <input type="checkbox" checked={streamingSse} onChange={e => setStreamingSse(e.target.checked)} className="custom-switch" />
              </label>
            </div>

            <button className={`btn-execute ${isExecuting ? "loading" : ""}`} onClick={executeRequest}>
              <span className="btn-icon">{isExecuting ? "⏳" : "🚀"}</span>
              <span>{isExecuting ? "Processing..." : "Execute Proxy Request"}</span>
            </button>
          </div>

          {errorMessage && (
            <div className="error-alert">
              ⚠️ {errorMessage}
            </div>
          )}

          {/* 3 Panel Grid */}
          <div className="inspection-grid">
            
            {/* Panel 1: Input Prompt & Spans */}
            <div className="glass-card">
              <div className="card-header">
                <div className="card-title">
                  <span className="step-num">1</span>
                  <h3>Input Prompt & Entity Spans</h3>
                </div>
                <span className="pill-badge pill-cyan">Real-Time Extraction</span>
              </div>

              <div className="card-body">
                <label className="field-label">Raw User Input Prompt:</label>
                <textarea rows="4" spellCheck="false" value={inputPrompt} onChange={handleInputChange} placeholder="Type prompt or select scenario above..." />

                <label className="field-label margin-top">Detected PII & Secret Spans:</label>
                <div className="highlight-container">
                  {renderSpanContainer()}
                </div>
              </div>
            </div>

            {/* Panel 2: What Cloud Saw */}
            <div className="glass-card">
              <div className="card-header">
                <div className="card-title">
                  <span className="step-num step-cloud">2</span>
                  <h3>What Cloud Saw (Masked Request)</h3>
                </div>
                <span className="pill-badge pill-amber">Upstream LLM View</span>
              </div>
              <div className="card-body">
                <label className="field-label">Payload Sent to Cloud Server:</label>
                <div className="code-viewport">
                  {renderCloudSawText()}
                </div>
              </div>
            </div>

            {/* Panel 3: Restored Client Reply */}
            <div className="glass-card">
              <div className="card-header">
                <div className="card-title">
                  <span className="step-num step-client">3</span>
                  <h3>Restored Client Reply</h3>
                </div>
                <span className="pill-badge pill-emerald">Zero-Loss Restoration</span>
              </div>
              <div className="card-body">
                <label className="field-label">Final Restored Response to Client:</label>
                <div className="code-viewport viewport-emerald">
                  {restoredReply}
                </div>
              </div>
            </div>
          </div>

          {/* Receipt & Latency Section */}
          <div className="meta-grid">
            <div className="glass-card">
              <div className="card-header">
                <div className="card-title">
                  <h3>X-Vault-Report Privacy Receipt</h3>
                </div>
                <span className="pill-badge pill-purple">HTTP Header Audit</span>
              </div>
              <div className="card-body">
                <pre className="code-viewport json-view">
                  {JSON.stringify(receipt, null, 2)}
                </pre>
              </div>
            </div>

            <div className="glass-card">
              <div className="card-header">
                <div className="card-title">
                  <h3>Latency & Execution Breakdown</h3>
                </div>
                <span className="pill-badge pill-cyan">Performance Metrics</span>
              </div>
              <div className="card-body">
                <div className="latency-cards">
                  <div className="latency-card">
                    <span className="lat-label">Rules Engine</span>
                    <span className="lat-value">{timings.rules} ms</span>
                    <span className="lat-sub">Regex & Verhoeff</span>
                  </div>

                  <div className="latency-card">
                    <span className="lat-label">Gemma SLM</span>
                    <span className="lat-value">{timings.gemma} ms</span>
                    <span className="lat-sub">Semantic Context</span>
                  </div>

                  <div className="latency-card">
                    <span className="lat-label">Upstream API</span>
                    <span className="lat-value">{timings.upstream} ms</span>
                    <span className="lat-sub">LLM Inference</span>
                  </div>

                  <div className="latency-card">
                    <span className="lat-label">Token Restore</span>
                    <span className="lat-value">{timings.restore} ms</span>
                    <span className="lat-sub">Client Reconstruction</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      )}

      {/* TAB 2: GEMMA IMPACT */}
      {activeTab === "gemma" && (
        <section className="tab-content active">
          <div className="section-banner">
            <h2>🧠 Gemma SLM Layer Intelligence Analysis</h2>
            <p>Evaluate baseline regex rules against combined Rules + Gemma model intelligence on ambiguous or unstructured inputs.</p>
            <button className="btn-action" onClick={runGemmaImpact}>
              {gemmaImpact.loading ? "Evaluating..." : "Run SLM Intelligence Evaluation"}
            </button>
          </div>

          <div className="dual-grid">
            <div className="glass-card">
              <div className="card-header">
                <h3>Rules Engine Alone (Baseline Regex)</h3>
              </div>
              <pre className="code-viewport">
                {gemmaImpact.rules ? JSON.stringify(gemmaImpact.rules, null, 2) : "Click button above to evaluate..."}
              </pre>
            </div>

            <div className="glass-card">
              <div className="card-header">
                <h3>Rules + Gemma SLM Layer (Hybrid Engine)</h3>
              </div>
              <pre className="code-viewport viewport-cyan">
                {gemmaImpact.combo ? JSON.stringify(gemmaImpact.combo, null, 2) : "Click button above to evaluate..."}
              </pre>
            </div>
          </div>
        </section>
      )}

      {/* TAB 3: COMPARE RAW VS MASKED */}
      {activeTab === "compare" && (
        <section className="tab-content active">
          <div className="section-banner">
            <h2>🔒 Raw Data Leak vs VaultProxy Masked Protection</h2>
            <p>Demonstrate what cloud servers see when VaultProxy is disabled (RAW PII Leak) vs enabled (Vault Tokenized).</p>
            <button className="btn-action" onClick={runCompareTest}>
              {compareData.loading ? "Running test..." : "Run Side-by-Side Cloud Request Test"}
            </button>
          </div>

          <div className="dual-grid">
            <div className="glass-card border-danger">
              <div className="card-header">
                <h3 className="text-danger">⚠️ Proxy OFF — Raw PII Leaked to Upstream</h3>
                <span className="pill-badge pill-red">Privacy Breach</span>
              </div>
              <pre className="code-viewport viewport-red">
                {compareData.raw || "Click button above to execute..."}
              </pre>
            </div>

            <div className="glass-card border-success">
              <div className="card-header">
                <h3 className="text-success">🛡️ Proxy ON — Vault Token Placeholder Protection</h3>
                <span className="pill-badge pill-emerald">Zero-Trust Secured</span>
              </div>
              <pre className="code-viewport viewport-emerald">
                {compareData.masked || "Click button above to execute..."}
              </pre>
            </div>
          </div>
        </section>
      )}

      {/* TAB 4: STREAM TRACE */}
      {activeTab === "streaming" && (
        <section className="tab-content active">
          <div className="section-banner">
            <h2>🌊 Streaming Token Restorer Trace</h2>
            <p>Observe real-time SSE chunk stream buffering in <code>StreamRestorer</code> when token brackets are split across chunk boundaries.</p>
            <button className="btn-action" onClick={runStreamTrace}>
              {isTracing ? "Tracing Stream..." : "Start Live SSE Stream Trace"}
            </button>
          </div>

          <div className="glass-card">
            <div className="table-container">
              <table className="trace-table">
                <thead>
                  <tr>
                    <th style={{ width: "60px" }}>#</th>
                    <th>Incoming SSE Upstream Chunk</th>
                    <th>Held Buffer (Partial Token Hold)</th>
                    <th>Emitted Restored Text</th>
                  </tr>
                </thead>
                <tbody>
                  {traceRows.length === 0 ? (
                    <tr><td colSpan="4" className="empty-row">Click "Start Live SSE Stream Trace" to observe stream buffering.</td></tr>
                  ) : (
                    traceRows.map((r, i) => (
                      <tr key={i}>
                        <td>#{r.step}</td>
                        <td><code>{r.chunk || "—"}</code></td>
                        <td>{r.buffer ? <span className="held-buffer-tag">{r.buffer}</span> : "—"}</td>
                        <td>{r.emitted ? <span className="emitted-tag">{r.emitted}</span> : "—"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* TAB 5: FAILURE MODES */}
      {activeTab === "failure" && (
        <section className="tab-content active">
          <div className="section-banner">
            <h2>🛡️ Fail-Closed Safety & Degraded State Simulation</h2>
            <p>Simulate a Gemma SLM connection error or timeout to test VaultProxy degraded fallback vs Strict Mode 503 response.</p>
            <div className="sim-controls">
              <button className="btn-sim-danger" onClick={() => simulateGemma("gemma_down")}>🔴 Simulate Gemma Timeout</button>
              <button className="btn-sim-success" onClick={() => simulateGemma("reset")}>🟢 Reset Engine Normal</button>
              <span className={`sim-badge ${status.simulated_gemma_down ? "border-danger text-danger" : ""}`}>
                Status: {status.simulated_gemma_down ? "🔴 Simulated Gemma Timeout" : "🟢 Normal Operation"}
              </span>
            </div>
          </div>

          <div className="dual-grid">
            <div className="glass-card">
              <div className="card-header">
                <h3>STRICT_MODE = false (Graceful Degraded Fallback)</h3>
              </div>
              <p className="desc-text">Rules-based masking continues. Receipt header marks <code>degraded: true</code>.</p>
              <button className="btn-action-sec" onClick={() => runFailureTest(false)}>Test Degraded Mode</button>
              <pre className="code-viewport">
                {failResult.nonStrict || "Result will appear here..."}
              </pre>
            </div>

            <div className="glass-card border-danger">
              <div className="card-header">
                <h3 className="text-danger">STRICT_MODE = true (Fail-Closed HTTP 503)</h3>
              </div>
              <p className="desc-text">Blocks request immediately. Zero PII transmitted. Returns HTTP 503 Service Unavailable.</p>
              <button className="btn-sim-danger" onClick={() => runFailureTest(true)}>Test Strict Fail-Closed (503)</button>
              <pre className="code-viewport viewport-red">
                {failResult.strict || "Result will appear here..."}
              </pre>
            </div>
          </div>
        </section>
      )}

      {/* TAB 6: BENCHMARK SUITE */}
      {activeTab === "benchmark" && (
        <section className="tab-content active">
          <div className="section-banner">
            <h2>📊 Redaction Benchmark Suite Metrics</h2>
            <p>Precision, Recall, and F1 performance evaluated across synthetic seeded data and held-out Indian PII evaluation sets.</p>
            <button className="btn-action-sec" onClick={fetchBenchmark}>
              {benchmark.loading ? "Loading Metrics..." : "Refresh Benchmark Metrics"}
            </button>
          </div>

          <div className="glass-card">
            {benchmark.loading ? (
              <div className="empty-row">Loading benchmark metrics...</div>
            ) : benchmark.metrics ? (
              <table className="bench-table">
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>Sample Count</th>
                    <th>Precision</th>
                    <th>Recall</th>
                    <th>F1 Score</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.keys(benchmark.metrics).map((ds) => {
                    const m = benchmark.metrics[ds];
                    return (
                      <tr key={ds}>
                        <td><strong>{ds.toUpperCase()}</strong></td>
                        <td>{m.total_samples || "—"}</td>
                        <td>{(m.precision * 100).toFixed(2)}%</td>
                        <td>{(m.recall * 100).toFixed(2)}%</td>
                        <td><strong>{(m.f1 * 100).toFixed(2)}%</strong></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            ) : (
              <div className="empty-row">Click "Refresh Benchmark Metrics" to view.</div>
            )}
          </div>
        </section>
      )}

    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
