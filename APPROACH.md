# Approach Note — Marksheet Extractor API

## 1. Extraction Approach

### Input pipeline

| Step | Tool | Rationale |
|---|---|---|
| File validation | Python stdlib | Extension + size check before any heavy processing |
| PDF → images | **PyMuPDF** (fitz) @ 200 DPI | Reliable rendering of complex layouts; open-source |
| Image preprocessing | **Pillow** | Normalise colour mode, downscale to ≤ 2048 px, contrast +20 %, sharpen |
| LLM extraction | **Google Gemini 1.5 Flash** | Native vision; handles tables, varied layouts, multiple pages in one call |

All PDF pages are sent to Gemini in a **single API call**, allowing the model to reason holistically across pages (e.g., totals on page 2, subjects on page 1).

### Why not pure OCR?

Traditional OCR (Tesseract, etc.) extracts raw text but loses table structure, cannot semantically group rows, and fails on handwritten or low-quality scans.  Gemini understands document layout semantically, so "subject", "max marks", and "obtained marks" are correctly associated even when column headers are absent or abbreviated.

---

## 2. Confidence Scoring Methodology

Confidence is a **two-stage calibrated** score in [0, 1] per extracted field.

### Stage 1 — LLM self-assessment (weight: 70 %)

The extraction prompt instructs Gemini to rate each field on three sub-factors:

| Sub-factor | Weight | Description |
|---|---|---|
| Visibility | 35 % | How clearly is the text readable in the image? |
| Certainty | 40 % | How confident is the model about the extracted value? |
| Consistency | 25 % | Does the value make logical sense in document context? |

Gemini combines these into a single `confidence` float it writes into the JSON response.

### Stage 2 — Format validation (weight: 30 %)

Post-processing deterministic checks produce a `format_score` per field type:

| Field type | High confidence (1.0) | Penalised |
|---|---|---|
| `dob` | ISO `YYYY-MM-DD` format | Unrecognised format → 0.4 |
| `percentage` | Float in [0, 100] | Out of range → 0.2 |
| `marks` | Non-negative number | Non-numeric → 0.3 |
| `year` | 4-digit, 1950–2035 | Outside range → 0.3 |
| `name` | Length ≥ 2 chars | Very short → 0.3 |
| null / absent | — | Always 0.0 |

### Final calibrated score

```
final_confidence = 0.70 × llm_confidence + 0.30 × format_score
```

**Why blend?**  LLMs can be overconfident on fields they hallucinate.  Format validation acts as a reality-check: a date extracted as "31/13/2023" (impossible month) will have a lower format score and therefore a lower final confidence even if Gemini rated it highly.

---

## 3. LLM Choice: Google Gemini 1.5 Flash

### Selection rationale

| Factor | Gemini 1.5 Flash | Alternatives considered |
|---|---|---|
| **Vision quality** | Excellent — designed for document understanding | GPT-4o: similar; LLaMA: weaker on structured tables |
| **Multi-image call** | All pages in one request; holistic reasoning | — |
| **JSON mode** | `response_mime_type="application/json"` forces valid JSON | Requires prompt engineering with others |
| **Speed** | ~2–4 s per marksheet | GPT-4o: slower; LLaMA local: depends on GPU |
| **Cost** | Free tier available; ~$0.075 / 1M tokens | GPT-4o: ~$5 / 1M tokens |
| **Open-source compliance** | Commercial API — allowed per assignment rules | — |

### Why not GPT-4o?
Cost is ~60× higher with equivalent accuracy for this use case.

### Why not LLaMA (local)?
Requires GPU infrastructure, is significantly slower, and open-source vision models lag behind frontier models on complex table extraction from real-world scans.

---

## 4. Design Choices

### FastAPI
- Native `async` / `await` support — critical for concurrent batch processing
- Auto-generated Swagger UI is ideal for evaluation
- Pydantic v2 for type-safe schemas with no extra validation code

### Async batch processing
`asyncio.gather()` fans out N file extractions concurrently.  Each extracts independently, so a single failure returns a `"failed"` entry without blocking the rest.  Gemini API rate limits apply per key, but parallel requests are handled gracefully by the SDK.

### JWT authentication
Stateless Bearer tokens require no database or session storage.  The standard OAuth2 `password` grant is used, which Swagger UI understands natively (the "Authorize" padlock).

### Pydantic-settings for configuration
All secrets come from environment variables / `.env` file.  `@lru_cache` on `get_settings()` ensures the file is read once, not on every request.

### PDF rendering at 200 DPI
- Below 150 DPI: small text becomes illegible to the LLM, accuracy drops significantly.
- Above 300 DPI: image size grows rapidly (slow uploads to Gemini API) with diminishing accuracy returns.
- 200 DPI is the empirically validated sweet spot for A4/Letter marksheets.

### Pillow preprocessing
Light contrast enhancement (1.2×) and sharpening improve legibility of faded or low-contrast scans without distorting the image enough to introduce OCR artefacts.

### Security
- File extension and size checked _before_ any decoding or LLM call.
- No user-supplied content is ever executed or eval'd.
- CORS is open for demo purposes; restrict `allow_origins` for production.
- Credentials are not logged.
