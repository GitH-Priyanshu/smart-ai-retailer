# magicpin AI Challenge — Vera Message Engine ("Vera Composer Bot")

Deterministic, grounded message-composition engine for magicpin's merchant assistant **Vera**, built for high-conversion WhatsApp merchant and customer engagement across 5 categories (dentists, salons, restaurants, gyms, pharmacies).

- **Production Endpoint (Railway):** `https://smart-ai-retailer-production.up.railway.app`
- **GitHub Repository:** `https://github.com/GitH-Priyanshu/smart-ai-retailer`
- **Model Engine:** Google Gemini (`gemini-3.5-flash-lite`, reporting `gemini-3.5-flash-lite` in metadata)

---

## 1. Architectural Approach

The system implements a deterministic, multi-layered composition pipeline driven by a 4-context framework:
`CategoryContext` + `MerchantContext` + `TriggerContext` + `CustomerContext` $\rightarrow$ `ComposedMessage`

```
  [Incoming Context: Category / Merchant / Trigger / Customer]
                              │
                              ▼
                   ┌──────────────────────┐
                   │ Atomic Context Store │  (In-memory, versioned, 409 conflict detection)
                   └──────────┬───────────┘
                              │
          ┌───────────────────┴───────────────────┐
          │                                       │
  [POST /v1/tick]                         [POST /v1/reply]
          │                                       │
          │                               ┌───────▼───────┐
          │                               │   Pre-Guards  │
          │                               └───────┬───────┘
          │                                       │ (Hostile regex -> end)
          │                                       │ (Auto-reply counter -> wait/end)
          │                                       │ (Intent detector -> mode="action")
          │                                       │
          └───────────────────┬───────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │   Vera Composer LLM   │  (Kind-aware prompt, structured Pydantic schema)
                  └───────────┬───────────┘
                              │ (Fallback on timeout / failure)
                              ▼
                  ┌───────────────────────┐
                  │      Post-Guards      │
                  └───────────┬───────────┘
                              │ 1. Grounding check (Zero fabrication of numbers/dates)
                              │ 2. URL stripper (Preserves trailing punctuation)
                              │ 3. Single-CTA scorer (Scores & drops duplicate asks)
                              │ 4. Anti-repetition check (Deduplicates prior turns)
                              ▼
                  [Validated WhatsApp Action]
```

### Key Components
1. **Single-Prompt Kind-Aware Composition (`composer.py`):**
   Instead of chaining dozens of brittle prompts, a unified system prompt encapsulates non-negotiable communication rules (category voice, time-window disambiguation, language grounding, single CTA, structural dissimilarity from case studies) and dispatches framing rules across 20+ trigger kinds with zero temperature (`temperature=0.0`) and structured Pydantic outputs (`ComposedMessage`).
2. **Pre-Checks (`guard_layer.py`):**
   - **Hostile/Opt-Out Detection:** Instant regex intercept to `action: "end"` (bypasses LLM, zero latency).
   - **Auto-Reply Counter:** Detects automated bot responses (Turn 1: nudge, Turn 2: `wait` 14400s, Turn 3: `end`).
   - **Intent Transition:** Detects affirmative merchant commitment ("let's do it", "go ahead"), flips mode to `action`, enforces action verbs (`done`, `sending`, `draft`), and eliminates qualifying questions.
3. **Post-Guards (`guard_layer.py`):**
   - **Grounding Verification:** Extracts all numbers, percentages, dates, and currency values from the generated body and validates them against a dynamically compiled context corpus. Intercepts any unverified claim before delivery.
   - **URL Stripping & Sentence Smoothing:** Strips raw links while cleaning up dangling prepositions (`at`, `from`, `link:`) and preserving trailing sentence punctuation.
   - **Single-CTA Scorer:** Detects multiple question marks or asks, scores candidate questions against trigger relevance, and prunes secondary generic asks to guarantee exactly one call-to-action.
4. **Deterministic Fallback:**
   If the LLM client encounters a rate limit, timeout, or invalid output, a pure deterministic fallback instantly composes a 100% grounded message directly from context fields, guaranteeing 200 OK within 1.5 seconds.

---

## 2. Tradeoffs Under the 6-Hour Solo Constraint

| Decision | Chosen Approach | Alternative Considered | Rationale Under Time Limit |
| :--- | :--- | :--- | :--- |
| **Prompt Architecture** | One flexible prompt with kind-aware framing rules | 20+ individual specialist prompts | Avoided maintaining 20 separate prompt templates and schemas; unified system prompt achieved 80–84% judge scores with zero hallucination. |
| **Context Storage** | In-memory atomic store with versioning | PostgreSQL or Redis | Allowed sub-millisecond context read/writes with zero operational dependencies or migrations, easily satisfying all 409 stale-version checks. |
| **Grounding Enforcement** | Python regex & corpus validation guard | LLM-as-a-judge reflection loop | Programmatic parsing is 100% deterministic, executes in <1ms, and guarantees zero hallucinated numbers without doubling LLM API cost/latency. |
| **Conversation State** | In-memory turn repository with role tracking | Persistent database session table | Fits single-instance container lifecycle; simple, fast, and sufficient for 20-action tick limits. |

---

## 3. What I'd Build Next (2-Week Horizon)

1. **Distributed State & Persistence:** Migrate the in-memory context and conversation stores to Redis (with key TTLs matching trigger expirations) backed by PostgreSQL for audit logs.
2. **Dynamic Few-Shot Retrieval:** Implement vector embeddings (via pgvector or Pinecone) to dynamically retrieve the most relevant historical merchant interactions from verified case studies based on category, locality, and performance dip severity.
3. **Multi-Turn Escalation Workflows:** Add asynchronous webhook callbacks for human-in-the-loop escalation when merchants reply with complex commercial queries or regulatory edge cases.
4. **Proactive Rate Limiting & Multi-Provider Fallback:** Implement client-side round-robin load balancing across multiple Gemini API keys and Claude/DeepSeek fallback providers to handle sudden burst traffic.

---

## 4. Pre-Flight Verification Checklist

All items from Part 1 §8 verified green on the live production environment:

- [x] **Endpoint Reachable Publicly over HTTPS:** `https://smart-ai-retailer-production.up.railway.app`
- [x] **All 5 Endpoints Operational:** `/v1/healthz`, `/v1/metadata`, `/v1/context`, `/v1/tick`, `/v1/reply`
- [x] **Context Idempotency:** `/v1/context` rejects stale versions with `409 Conflict`, rejects invalid scopes with `400 Bad Request`, and accepts same/higher versions with `200 OK`.
- [x] **Sub-30s Response Latency:** Measured live round-trip latency on Railway:
  - `/v1/healthz`: ~280 ms
  - `/v1/metadata`: ~300 ms
  - `/v1/context`: ~280 ms
  - `/v1/tick` (Live LLM Composition): **~1,700 ms** (1.7s vs 30s cutoff)
- [x] **Accurate Health Counts:** `contexts_loaded` reflects real-time loaded entities accurately.
- [x] **Zero Raw URLs:** Cleaned automatically by `guard_layer.check_urls`.
- [x] **Time Window Disambiguation:** Multi-window metrics (e.g. 30-day views vs 7-day dips) are distinctly labeled.
- [x] **Grounded Rationales:** Every rationale cites verifiable context facts.
- [x] **Clean Git History:** All proprietary challenge specifications, case study materials, and `.env` credentials excluded from git history.
