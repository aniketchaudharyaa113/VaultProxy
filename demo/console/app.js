// VaultProxy Judge Console Controller
let debounceTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  setInterval(fetchStatus, 4000);
  loadPreset("loan");
});

function switchTab(tabId) {
  document.querySelectorAll(".nav-tab").forEach((btn) => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((ct) => ct.classList.remove("active"));

  if (event && event.currentTarget) {
    event.currentTarget.classList.add("active");
  }
  
  const targetTab = document.getElementById(`tab-${tabId}`);
  if (targetTab) {
    targetTab.classList.add("active");
  }

  if (tabId === "benchmark") {
    loadBenchmark();
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/demo/status");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("chipGemmaBackend").innerHTML = `<span class="chip-dot"></span>Gemma: ${data.gemma_backend}`;

    const reachEl = document.getElementById("chipReachable");
    if (data.reachable) {
      reachEl.innerHTML = `<span class="chip-dot"></span>Status: ${data.model_name} (Ready)`;
      reachEl.className = "chip active-green";
    } else {
      reachEl.innerHTML = `<span class="chip-dot"></span>Status: ${data.gemma_backend === "off" ? "Off" : "Unreachable"}`;
      reachEl.className = data.gemma_backend === "off" ? "chip" : "chip active-red";
    }

    document.getElementById("chipStrict").innerHTML = `<span class="chip-dot"></span>Strict: ${data.strict_mode}`;
    document.getElementById("chipDemo").innerHTML = `<span class="chip-dot"></span>Demo: ${data.demo_mode ? "ON" : "OFF"}`;
    document.getElementById("chipUpstream").innerHTML = `<span class="chip-dot"></span>Upstream: ${data.upstream_host}`;
  } catch (e) {
    console.error("Status fetch failed", e);
  }
}

// Verhoeff checksum algorithm for dynamic fake Aadhaar generation
const d_table = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
  [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
  [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
  [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
  [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
  [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
  [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
  [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
  [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
];
const p_table = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
  [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
  [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
  [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
  [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
  [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
  [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
  [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]
];
const inv_table = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9];

function generateVerhoeff(prefix) {
  let c = 0;
  const reversed = prefix.split("").reverse();
  for (let i = 0; i < reversed.length; i++) {
    c = d_table[c][p_table[(i + 1) % 8][parseInt(reversed[i])]];
  }
  return inv_table[c];
}

function generateDynamicAadhaar() {
  const prefix = "36759834120";
  const check = generateVerhoeff(prefix);
  return prefix + check;
}

function loadPreset(key, evt) {
  if (evt && evt.currentTarget) {
    document.querySelectorAll(".preset-btn").forEach(b => b.classList.remove("active"));
    evt.currentTarget.classList.add("active");
  }

  const aadhaar = generateDynamicAadhaar();
  const presets = {
    loan: `Hello, I am applying for a personal loan. My name is Rajesh Sharma, residing at Flat 402, Green Glen Layout, Bellandur, Bengaluru. My Aadhaar is ${aadhaar}, PAN is ABCPB1234F, and mobile is 9876543210. Pay processing fee to rajesh@oksbi.`,
    hinglish: `Bhai Vikram ko bolo 9876543210 pe call kare. Uska PAN number XYZPH9876K and Aadhaar ${aadhaar} verify karna hai.`,
    devops: `[ERROR] Production deploy failed! AWS key AKIAIOSFODNN7EXAMPLE leaked in log file. GitHub PAT token: github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz. Admin email: devsec@company.in`,
    negatives: `Order ID 123456789012 was processed. Invalid check number 367598341209 and bad PAN ABCXX1234F should be ignored. Product code SBIN1001234 is not IFSC.`,
    bengali: `আমার আধার নম্বর ৩৬৭৫৯৮৩৪১২০৩ এবং মোবাইল ৯৮Nz৪৩২১০।`.replace("Nz", "৭৬৫")
  };

  const text = presets[key] || "";
  document.getElementById("liveInput").value = text;
  runAnalyze();
}

function debounceAnalyze() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(runAnalyze, 250);
}

async function runAnalyze() {
  const text = document.getElementById("liveInput").value;
  const useGemma = document.getElementById("toggleGemma").checked;

  try {
    const res = await fetch("/demo/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_gemma: useGemma })
    });
    if (!res.ok) {
      console.error("Analyze error status:", res.status);
      return;
    }
    const data = await res.json();
    renderSpans(text, data.spans);
  } catch (e) {
    console.error("Analyze error", e);
  }
}

function renderSpans(text, spans) {
  const box = document.getElementById("spanHighlightBox");
  if (!spans || spans.length === 0) {
    box.textContent = text || "No entities detected.";
    return;
  }

  let html = "";
  let lastIdx = 0;

  spans.forEach((span) => {
    html += escapeHtml(text.substring(lastIdx, span.start));
    const entityText = escapeHtml(text.substring(span.start, span.end));
    const srcClass = span.source === "rule" ? "src-rule" : "src-gemma";
    const srcLabel = span.source === "rule" ? "RULE" : "GEMMA";
    const tagClass = `tag-${span.type}`;
    const chkText = span.type === "AADHAAR" ? ` (Verhoeff: ${span.checksum_valid ? 'Valid' : 'Invalid'})` : "";

    html += `<span class="span-tag ${tagClass}" title="Type: ${span.type} | Source: ${span.source} | Score: ${span.score}">${entityText}<span class="src-badge ${srcClass}">${srcLabel}</span>${chkText}</span>`;
    lastIdx = span.end;
  });

  html += escapeHtml(text.substring(lastIdx));
  box.innerHTML = html;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function runLiveRequest() {
  const btn = document.getElementById("btnRunRequest");
  const text = document.getElementById("liveInput").value;
  const proxy = document.getElementById("toggleProxy").checked;
  const useGemma = document.getElementById("toggleGemma").checked;
  const strict = document.getElementById("toggleStrict").checked;
  const stream = document.getElementById("toggleStream").checked;

  btn.classList.add("loading");
  btn.innerHTML = `<span class="btn-icon">⏳</span> Processing Proxy Request...`;

  document.getElementById("liveCloudSaw").textContent = "Encrypting & tokenizing payload for cloud upstream...";
  document.getElementById("liveRestoredReply").textContent = "Awaiting response & restoring tokenized values...";

  try {
    const res = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy, use_gemma: useGemma, strict, stream })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      const detailMsg = errData.detail || "Proxy server request error";
      document.getElementById("liveCloudSaw").textContent = `Request terminated with status ${res.status}`;
      document.getElementById("liveRestoredReply").innerHTML = `<div class="text-danger"><strong>HTTP ${res.status} Error:</strong><br>${escapeHtml(detailMsg)}</div>`;
      return;
    }

    const data = await res.json();

    // Highlight masked tokens in cloud saw HTML
    let cloudSawHtml = escapeHtml(data.cloud_saw);
    cloudSawHtml = cloudSawHtml.replace(/(\\[[A-Z_]+_\d+\\])/g, '<span class="cloud-token-highlight">$1</span>');
    document.getElementById("liveCloudSaw").innerHTML = cloudSawHtml;

    document.getElementById("liveRestoredReply").textContent = data.restored_reply;
    document.getElementById("liveReceipt").textContent = JSON.stringify(data.receipt, null, 2);

    document.getElementById("timeRules").textContent = `${data.timings_ms.rules} ms`;
    document.getElementById("timeGemma").textContent = `${data.timings_ms.gemma} ms`;
    document.getElementById("timeUpstream").textContent = `${data.timings_ms.upstream} ms`;
    document.getElementById("timeRestore").textContent = `${data.timings_ms.restore} ms`;
  } catch (e) {
    document.getElementById("liveRestoredReply").innerHTML = `<div class="text-danger">Network Error: ${escapeHtml(e.message)}</div>`;
  } finally {
    btn.classList.remove("loading");
    btn.innerHTML = `<span class="btn-icon">🚀</span> Execute Proxy Request`;
  }
}

async function runGemmaImpact() {
  const text = document.getElementById("liveInput").value;
  
  document.getElementById("gemmaImpactRules").textContent = "Running baseline regex analysis...";
  document.getElementById("gemmaImpactCombo").textContent = "Running combined Gemma SLM evaluation...";

  try {
    const resRules = await fetch("/demo/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_gemma: false })
    });
    const dataRules = await resRules.json();

    const resCombo = await fetch("/demo/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_gemma: true })
    });
    const dataCombo = await resCombo.json();

    document.getElementById("gemmaImpactRules").textContent = JSON.stringify(dataRules.spans, null, 2);
    document.getElementById("gemmaImpactCombo").textContent = JSON.stringify(dataCombo.spans, null, 2);

    const rulesCount = dataRules.spans.length;
    const comboCount = dataCombo.spans.length;
    const gemmaFound = dataCombo.spans.filter(s => s.source === "gemma").length;

    document.getElementById("gemmaSummaryText").innerHTML = `
      <strong>Analysis Result:</strong> Baseline regex extracted <strong>${rulesCount}</strong> spans.<br>
      Combined engine extracted <strong>${comboCount}</strong> spans (including <strong>${gemmaFound}</strong> complex/ambiguous spans captured by Gemma SLM).
    `;
  } catch (e) {
    console.error("Gemma impact evaluation failed", e);
  }
}

async function runCompareTest() {
  const text = document.getElementById("liveInput").value;

  document.getElementById("compareRawCloud").textContent = "Executing raw request (Proxy OFF)...";
  document.getElementById("compareMaskedCloud").textContent = "Executing tokenized request (Proxy ON)...";

  try {
    const rawRes = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: false, stream: false })
    });
    const rawData = await rawRes.json();
    document.getElementById("compareRawCloud").textContent = rawData.cloud_saw;

    const maskedRes = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: true, stream: false })
    });
    const maskedData = await maskedRes.json();
    
    let cloudSawHtml = escapeHtml(maskedData.cloud_saw);
    cloudSawHtml = cloudSawHtml.replace(/(\\[[A-Z_]+_\d+\\])/g, '<span class="cloud-token-highlight">$1</span>');
    document.getElementById("compareMaskedCloud").innerHTML = cloudSawHtml;
  } catch (e) {
    console.error("Compare test failed", e);
  }
}

async function runStreamTrace() {
  const text = document.getElementById("liveInput").value;
  const tbody = document.getElementById("traceTableBody");
  tbody.innerHTML = `<tr><td colspan="4" class="empty-row">Connecting to stream trace...</td></tr>`;

  try {
    const res = await fetch("/demo/stream-trace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let step = 1;
    tbody.innerHTML = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunkStr = decoder.decode(value);
      const lines = chunkStr.split("\n");

      for (let line of lines) {
        line = line.strip ? line.strip() : line.trim();
        if (!line.startsWith("data: ")) continue;
        const payloadStr = line.substring(6).trim();
        if (payloadStr === "[DONE]") break;

        try {
          const item = JSON.parse(payloadStr);
          const tr = document.createElement("tr");
          const chunkDisp = escapeHtml(item.upstream_chunk || "—");
          const bufferDisp = item.held_buffer ? `<span class="held-buffer-tag">${escapeHtml(item.held_buffer)}</span>` : "—";
          const emittedDisp = item.emitted ? `<span class="emitted-tag">${escapeHtml(item.emitted)}</span>` : "—";

          tr.innerHTML = `
            <td>#${step++}</td>
            <td><code>${chunkDisp}</code></td>
            <td>${bufferDisp}</td>
            <td>${emittedDisp}</td>
          `;
          tbody.appendChild(tr);
        } catch (err) {}
      }
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="text-danger">Stream trace error: ${escapeHtml(e.message)}</td></tr>`;
  }
}

async function simulateGemmaMode(mode) {
  try {
    const res = await fetch("/demo/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode })
    });
    const data = await res.json();
    const statusEl = document.getElementById("simStatus");
    if (data.simulated_gemma_down) {
      statusEl.textContent = "Status: 🔴 Simulated Gemma SLM Connection Timeout";
      statusEl.className = "sim-badge border-danger text-danger";
    } else {
      statusEl.textContent = "Status: 🟢 Normal Engine Operation";
      statusEl.className = "sim-badge";
    }
  } catch (e) {
    console.error("Simulate request failed", e);
  }
}

async function runFailureTest(strict) {
  const text = document.getElementById("liveInput").value;
  const targetId = strict ? "failStrictOut" : "failNonStrictOut";
  const el = document.getElementById(targetId);
  el.textContent = "Executing failure test...";

  try {
    const res = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: true, use_gemma: true, strict })
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({ detail: res.statusText }));
      el.textContent = `HTTP ${res.status}: ${JSON.stringify(errData, null, 2)}`;
      return;
    }

    const data = await res.json();
    el.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    el.textContent = `Error: ${e.message}`;
  }
}

async function loadBenchmark() {
  const box = document.getElementById("benchTableBox");
  box.textContent = "Fetching latest benchmark evaluation metrics...";

  try {
    const res = await fetch("/demo/benchmark");
    const data = await res.json();

    if (data.error) {
      box.textContent = data.error;
      return;
    }

    let html = `
      <table class="bench-table">
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
    `;

    for (let ds in data.metrics) {
      const m = data.metrics[ds];
      html += `
        <tr>
          <td><strong>${ds.toUpperCase()}</strong></td>
          <td>${m.total_samples || '—'}</td>
          <td>${(m.precision * 100).toFixed(2)}%</td>
          <td>${(m.recall * 100).toFixed(2)}%</td>
          <td><strong>${(m.f1 * 100).toFixed(2)}%</strong></td>
        </tr>
      `;
    }

    html += `</tbody></table>`;
    box.innerHTML = html;
  } catch (e) {
    box.textContent = `Failed to load benchmark: ${e.message}`;
  }
}
