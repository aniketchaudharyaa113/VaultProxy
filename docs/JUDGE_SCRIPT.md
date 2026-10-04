# VaultProxy 3-Minute Judge Presentation & Q&A Guide 🏆

Welcome judges! VaultProxy is a local-first, privacy-preserving proxy for LLM applications focused on Indian PII (Aadhaar, PAN, Mobile, UPI, IFSC, Email, Secrets).

---

## ⏱️ 3-Minute Live Demo Script

### Minute 1: The Problem & Live Protection (Tab: "Live Proxy" & "Raw vs Masked")
1. Open `http://localhost:8000/demo`. Point out the header chips showing `Gemma: off`, `Strict: false`, `Demo: true`.
2. Click **Preset 1 (Loan Application)**. Point to the highlighted entities:
   - **Aadhaar** (teal) with Verhoeff checksum validation status (`checksum_valid: true`).
   - **PAN** (amber), **Mobile** (green), **UPI** (purple).
3. Click **Tab "Raw vs Masked"** -> Click **"Run Side-by-Side Comparison"**:
   - Show **Proxy OFF**: The cloud sees raw PII (Leaked Aadhaar, PAN, phone).
   - Show **Proxy ON**: The cloud sees ONLY `[AADHAAR_1]`, `[PAN_1]`, `[MOBILE_1]`. The client gets back real restored values seamlessly!

### Minute 2: Gemma Layer Intelligence & Streaming Buffer (Tab: "Gemma Impact" & "Streaming")
1. Click **Tab "Gemma Impact"**:
   - Explain: Deterministic rules catch structured patterns (Aadhaar checksum, PAN, UPI handles).
   - The optional local Gemma layer (`GEMMA_BACKEND=ollama`) extracts unstructured names and addresses in Hinglish/Latin script.
   - Show verbatim verification guarantee: VaultProxy ignores any hallucinated/rewritten strings not present verbatim in original text.
2. Click **Tab "Stream Trace"** -> Click **"Start Trace"**:
   - Point to the **Held Buffer** column highlighting partial token brackets (e.g., `[PAN_`).
   - Explain: `StreamRestorer` holds back incomplete token brackets up to 24 chars across SSE chunks to guarantee seamless streaming token restoration without broken output.

### Minute 3: Fail-Closed Safety & Benchmark Honesty (Tab: "Failure Modes" & "Benchmark")
1. Click **Tab "Failure Modes"**:
   - Click **"Simulate Gemma Down"**.
   - Show **Strict Mode OFF**: Proxy continues with rule-based masking and returns `degraded: true` receipt header.
   - Show **Strict Mode ON**: Proxy returns **HTTP 503** and forwards **ZERO** data upstream. Fail closed!
2. Click **Tab "Benchmark Metrics"**:
   - Show the Precision (100%), Recall (88.1%), and F1 (93.67%) breakdown.
   - Read the caveat banner: *"Evaluated on synthetic seeded test dataset. See held-out set for offline verification."*

---

## 🙋‍♂️ 8 Likely Judge Questions & Honest Answers

### Q1: Is VaultProxy 100% safe against all PII leaks?
**Answer**: No privacy tool is 100% safe. VaultProxy is a **risk-reduction tool**. Deterministic rule-based detectors achieve 100% precision on structured formats (Aadhaar Verhoeff checksum, PAN, IFSC, UPI handles), while the Gemma layer assists with names and addresses.

### Q2: What happens if an upstream LLM mangles or changes a token like `[PAN_1]` to `[pan 1]`?
**Answer**: Token restoration is case-insensitive (restores `[pan_1]` or `[PAN_1]`). However, if an upstream model heavily mangles the token structure, the token will not match and will return as text. System prompts instruct the LLM to preserve placeholders verbatim.

### Q3: How do you validate Aadhaar numbers to avoid false positives on 12-digit numbers?
**Answer**: We implement the **Verhoeff checksum algorithm** directly in Python. 12-digit numbers that fail the Verhoeff checksum or start with digits 0–1 (like order IDs) are ignored.

### Q4: Does VaultProxy store prompts, replies, or PII in a database or logs?
**Answer**: No. VaultProxy operates strictly in-memory per request. The vault lives only for the lifetime of that specific HTTP request. Logs contain entity types and counts ONLY—never raw prompt text or PII.

### Q5: How do you handle streaming responses when a token is split across SSE chunks?
**Answer**: Our `StreamRestorer` maintains a 24-character look-behind buffer. If an SSE chunk ends with an unclosed bracket `[`, it holds back the partial token until the closing `]` arrives or the stream ends (`data: [DONE]`).

### Q6: What happens if the local Gemma SLM times out or crashes?
**Answer**: In `STRICT_MODE=true`, VaultProxy **fails closed**: returns HTTP 503 and forwards NOTHING upstream. In `STRICT_MODE=false`, it logs a warning, sets `degraded: true` in the receipt header, and continues with rule-based masking.

### Q7: Are the benchmark results generated or on real customer data?
**Answer**: The core benchmark dataset is synthetic data generated with `Faker` (en_IN) and fixed random seeds. We explicitly disclose this limitation and provide a held-out evaluation set format (`bench/heldout.jsonl`) for independent verification.

### Q8: Can VaultProxy redact sensitive images or audio files?
**Answer**: No. Non-text modalities are an explicit non-goal for VaultProxy core. VaultProxy focuses strictly on text and multi-part text elements in OpenAI-compatible JSON payloads.
