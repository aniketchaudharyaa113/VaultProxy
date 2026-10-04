// VaultProxy Judge Console Controller

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  setInterval(fetchStatus, 5000);
  loadPreset("loan");
});

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => btn.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach((ct) => ct.classList.remove("active"));

  event.target.classList.add("active");
  document.getElementById(`tab-${tabId}`).classList.add("active");

  if (tabId === "benchmark") {
    loadBenchmark();
  }
}

async function fetchStatus() {
  try {
    const res = await fetch("/demo/status");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("chipGemmaBackend").textContent = `Gemma: ${data.gemma_backend}`;

    const reachEl = document.getElementById("chipReachable");
    if (data.reachable) {
      reachEl.textContent = `Status: ${data.model_name} (Ready)`;
      reachEl.className = "chip active-green";
    } else {
      reachEl.textContent = `Status: ${data.gemma_backend === "off" ? "Off" : "Unreachable"}`;
      reachEl.className = data.gemma_backend === "off" ? "chip" : "chip active-red";
    }

    document.getElementById("chipStrict").textContent = `Strict: ${data.strict_mode}`;
    document.getElementById("chipDemo").textContent = `Demo: ${data.demo_mode}`;
    document.getElementById("chipUpstream").textContent = `Upstream: ${data.upstream_host}`;
  } catch (e) {
    console.error("Status fetch failed", e);
  }
}

// Verhoeff checksum algorithm in JS for dynamic fake Aadhaar generation
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

function loadPreset(key) {
  const aadhaar = generateDynamicAadhaar();
  const presets = {
    loan: `Hello, I am applying for a personal loan. My name is Rajesh Sharma, residing at Flat 402, Green Glen Layout, Bellandur, Bengaluru. My Aadhaar is ${aadhaar}, PAN is ABCPB1234F, and mobile is 9876543210. Pay processing fee to rajesh@oksbi.`,
    hinglish: `Bhai Vikram ko bolo 9876543210 pe call kare. Uska PAN number XYZPH9876K and Aadhaar ${aadhaar} verify karna hai.`,
    devops: `[ERROR] Production deploy failed! AWS key AKIAIOSFODNN7EXAMPLE leaked in log file. GitHub PAT token: github_pat_11AAAAAAA0123456789012_abcdefghijklmnopqrstuvwxyz. Admin email: devsec@company.in`,
    negatives: `Order ID 123456789012 was processed. Invalid check number 367598341209 and bad PAN ABCXX1234F should be ignored. Product code SBIN1001234 is not IFSC.`
  };

  const text = presets[key] || "";
  document.getElementById("liveInput").value = text;
  runAnalyze();
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
    const data = await res.json();
    renderSpans(text, data.spans);
  } catch (e) {
    console.error("Analyze error", e);
  }
}

function renderSpans(text, spans) {
  const box = document.getElementById("spanHighlightBox");
  if (!spans || spans.length === 0) {
    box.textContent = text;
    return;
  }

  let html = "";
  let lastIdx = 0;

  spans.forEach((span) => {
    html += escapeHtml(text.substring(lastIdx, span.start));
    const entityText = escapeHtml(text.substring(span.start, span.end));
    const badgeClass = span.source === "rule" ? "badge-rule" : "badge-gemma";
    const badgeLabel = span.source === "rule" ? "RULE" : "GEMMA";
    const chkText = span.type === "AADHAAR" ? ` | Verhoeff: ${span.checksum_valid}` : "";

    html += `<span class="span-entity entity-${span.type}" title="Type: ${span.type} | Source: ${span.source} | Score: ${span.score}${chkText}">${entityText}<span class="${badgeClass}">${badgeLabel}</span></span>`;
    lastIdx = span.end;
  });

  html += escapeHtml(text.substring(lastIdx));
  box.innerHTML = html;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function runLiveRequest() {
  const text = document.getElementById("liveInput").value;
  const proxy = document.getElementById("toggleProxy").checked;
  const useGemma = document.getElementById("toggleGemma").checked;
  const strict = document.getElementById("toggleStrict").checked;
  const stream = document.getElementById("toggleStream").checked;

  document.getElementById("liveCloudSaw").textContent = "Sending request...";
  document.getElementById("liveRestoredReply").textContent = "Waiting for response...";

  try {
    const res = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy, use_gemma: useGemma, strict, stream })
    });

    if (!res.ok) {
      const errText = await res.text();
      document.getElementById("liveRestoredReply").textContent = `HTTP ${res.status}: ${errText}`;
      return;
    }

    const data = await res.json();
    document.getElementById("liveCloudSaw").textContent = data.cloud_saw;
    document.getElementById("liveRestoredReply").textContent = data.restored_reply;
    document.getElementById("liveReceipt").textContent = JSON.stringify(data.receipt, null, 2);

    document.getElementById("timeRules").textContent = `${data.timings_ms.rules}ms`;
    document.getElementById("timeGemma").textContent = `${data.timings_ms.gemma}ms`;
    document.getElementById("timeUpstream").textContent = `${data.timings_ms.upstream}ms`;
    document.getElementById("timeRestore").textContent = `${data.timings_ms.restore}ms`;
  } catch (e) {
    document.getElementById("liveRestoredReply").textContent = "Error: " + e.message;
  }
}

async function runGemmaImpact() {
  const text = document.getElementById("liveInput").value;

  try {
    const rRules = await fetch("/demo/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_gemma: false })
    });
    const dataRules = await rRules.json();

    const rCombo = await fetch("/demo/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, use_gemma: true })
    });
    const dataCombo = await rCombo.json();

    document.getElementById("gemmaImpactRules").textContent = JSON.stringify(dataRules, null, 2);
    document.getElementById("gemmaImpactCombo").textContent = JSON.stringify(dataCombo, null, 2);

    const rulesTypes = dataRules.spans.map((s) => `${s.type}: "${s.text}"`);
    const comboTypes = dataCombo.spans.map((s) => `${s.type}: "${s.text}"`);

    const gemmaAdded = dataCombo.spans.filter((s) => s.source === "gemma").map((s) => `${s.type}: "${s.text}"`);

    let summary = `Rules alone detected: [${rulesTypes.join(", ")}].\n`;
    if (gemmaAdded.length > 0) {
      summary += `✨ Gemma added: [${gemmaAdded.join(", ")}] in ${dataCombo.timings_ms.gemma}ms.`;
    } else {
      summary += `Gemma layer added 0 extra entities (Gemma off or all covered by rules).`;
    }

    document.getElementById("gemmaSummaryText").textContent = summary;
  } catch (e) {
    document.getElementById("gemmaSummaryText").textContent = "Impact analysis error: " + e.message;
  }
}

async function runCompareTest() {
  const text = document.getElementById("liveInput").value;

  try {
    const rOff = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: false })
    });
    const dOff = await rOff.json();
    document.getElementById("compareRawCloud").textContent = dOff.cloud_saw;

    const rOn = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: true })
    });
    const dOn = await rOn.json();
    document.getElementById("compareMaskedCloud").textContent = dOn.cloud_saw;
  } catch (e) {
    console.error(e);
  }
}

async function runStreamTrace() {
  const text = document.getElementById("liveInput").value;
  const tbody = document.getElementById("traceTableBody");
  tbody.innerHTML = "";

  try {
    const response = await fetch("/demo/stream-trace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let count = 0;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const chunkStr = decoder.decode(value);
      const lines = chunkStr.split("\n");

      lines.forEach((line) => {
        if (line.startsWith("data: ")) {
          const payloadStr = line.substring(6).strip ? line.substring(6).strip() : line.substring(6).trim();
          if (payloadStr === "[DONE]") return;

          try {
            const event = JSON.parse(payloadStr);
            count++;
            const tr = document.createElement("tr");

            const heldHtml = event.held_buffer ? `<span class="held-highlight">${escapeHtml(event.held_buffer)}</span>` : "<em>empty</em>";

            tr.innerHTML = `
              <td>${count}</td>
              <td><code>${escapeHtml(event.upstream_chunk)}</code></td>
              <td>${heldHtml}</td>
              <td><code>${escapeHtml(event.emitted)}</code></td>
            `;
            tbody.appendChild(tr);
          } catch (err) {}
        }
      });
    }
  } catch (e) {
    console.error("Stream trace error", e);
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
      statusEl.textContent = "Status: 🔴 Gemma Connection DOWN (Simulated)";
      statusEl.className = "sim-status text-danger";
    } else {
      statusEl.textContent = "Status: 🟢 Normal Operation";
      statusEl.className = "sim-status text-success";
    }
  } catch (e) {
    console.error(e);
  }
}

async function runFailureTest(strict) {
  const text = document.getElementById("liveInput").value;
  const outEl = strict ? document.getElementById("failStrictOut") : document.getElementById("failNonStrictOut");
  outEl.textContent = "Running request...";

  try {
    const res = await fetch("/demo/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, proxy: true, use_gemma: true, strict })
    });

    if (!res.ok) {
      const errText = await res.text();
      outEl.textContent = `HTTP ${res.status}: ${errText}`;
      return;
    }

    const data = await res.json();
    outEl.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    outEl.textContent = "Error: " + e.message;
  }
}

async function loadBenchmark() {
  const box = document.getElementById("benchTableBox");
  box.textContent = "Fetching benchmark metrics...";

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
            <th>Entity Type</th>
            <th>Precision</th>
            <th>Recall</th>
            <th>F1 Score</th>
            <th>True Positives (TP)</th>
            <th>False Positives (FP)</th>
            <th>False Negatives (FN)</th>
          </tr>
        </thead>
        <tbody>
    `;

    Object.keys(data.metrics).forEach((type) => {
      const m = data.metrics[type];
      html += `
        <tr>
          <td><strong>${type}</strong></td>
          <td>${(m.precision * 100).toFixed(2)}%</td>
          <td>${(m.recall * 100).toFixed(2)}%</td>
          <td>${(m.f1 * 100).toFixed(2)}%</td>
          <td>${m.tp}</td>
          <td>${m.fp}</td>
          <td>${m.fn}</td>
        </tr>
      `;
    });

    const o = data.overall;
    html += `
        <tr style="background: var(--bg); font-weight: bold;">
          <td>OVERALL SUMMARY</td>
          <td>${(o.precision * 100).toFixed(2)}%</td>
          <td>${(o.recall * 100).toFixed(2)}%</td>
          <td>${(o.f1 * 100).toFixed(2)}%</td>
          <td>${o.tp}</td>
          <td>${o.fp}</td>
          <td>${o.fn}</td>
        </tr>
      </tbody>
    </table>
    `;

    box.innerHTML = html;
  } catch (e) {
    box.textContent = "Failed to load benchmark: " + e.message;
  }
}
