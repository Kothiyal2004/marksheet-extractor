# Marksheet Extractor API

An AI-powered REST API that extracts structured data from academic marksheets (images and PDFs) using **Google Gemini**'s native vision capabilities, returning every field with a calibrated confidence score.

---

## Features

| | |
|---|---|
| **Multi-format input** | JPG, PNG, multi-page PDF (≤ 10 MB) |
| **Rich extraction** | Candidate details · Subject-wise marks · Overall result · Document info |
| **Confidence scores** | Every field includes a 0–1 confidence score (two-stage calibration) |
| **JWT auth** | OAuth2 Bearer token flow; Swagger UI lock icon just works |
| **Batch endpoint** | Extract up to 10 marksheets concurrently in one request |
| **Interactive demo** | Web UI at `/demo` — drag-and-drop upload + live JSON viewer |
| **Auto docs** | Swagger UI at `/docs` · ReDoc at `/redoc` |

---

## Architecture

```
Client
  │
  ▼
FastAPI (app/main.py)
  │   JWT auth (app/auth.py)
  │
  ├─► POST /api/v1/extract  ──► Extraction Orchestrator (app/extract.py)
  └─► POST /api/v1/batch    ──►        │
                                       ├─ PDF Service   (PyMuPDF)
                                       ├─ OCR Service   (Pillow preprocessing)
                                       └─ LLM Service   (Google Gemini)
                                                │
                                         Gemini Vision API
                                    (structured JSON extraction)
```

---

## Quick Start

### Prerequisites
- Python 3.10+
- A **Google Gemini API key** — get one free at [Google AI Studio](https://aistudio.google.com/)

### 1 · Clone & install

```bash
git clone <repo-url>
cd marksheet-extractor

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2 · Configure

```bash
cp .env.example .env
# Open .env and set at minimum:
#   GEMINI_API_KEY=<your key>
#   SECRET_KEY=<random 32+ char string>
```

Generate a strong secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### 3 · Run

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:
- **Swagger UI**: http://localhost:8000/docs
- **Demo UI**: http://localhost:8000/demo

---

## Docker

```bash
cp .env.example .env   # edit with your values
docker-compose up --build
```

---

## API Reference

### Authentication

```bash
# Get a JWT token
curl -X POST http://localhost:8000/auth/token \
  -d "username=admin&password=admin123"

# Response
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

### Extract a single marksheet

```bash
curl -X POST http://localhost:8000/api/v1/extract \
  -H "Authorization: Bearer <token>" \
  -F "file=@marksheet.pdf"
```

**Response schema** (excerpt):

```jsonc
{
  "document_id": "marksheet-a1b2c3d4",
  "processed_at": "2024-06-01T10:30:00Z",
  "candidate_details": {
    "name":             { "value": "Ravi Kumar",    "confidence": 0.97 },
    "father_name":      { "value": "Suresh Kumar",  "confidence": 0.92 },
    "roll_no":          { "value": "1234567",        "confidence": 0.99 },
    "dob":              { "value": "2000-04-15",     "confidence": 0.88 },
    "board_university": { "value": "CBSE",           "confidence": 0.98 },
    // ...
  },
  "subjects": [
    {
      "subject_name":   { "value": "Mathematics", "confidence": 0.99 },
      "max_marks":      { "value": 100,            "confidence": 0.98 },
      "obtained_marks": { "value": 92,             "confidence": 0.97 },
      "grade":          { "value": "A1",           "confidence": 0.96 },
      "pass_fail":      { "value": "PASS",         "confidence": 0.99 }
    }
    // ...
  ],
  "overall_result": {
    "total_max_marks":      { "value": 500,            "confidence": 0.97 },
    "total_obtained_marks": { "value": 452,            "confidence": 0.96 },
    "percentage":           { "value": 90.4,           "confidence": 0.97 },
    "division":             { "value": "First Division","confidence": 0.93 },
    "result_status":        { "value": "PASS",         "confidence": 0.99 }
  },
  "document_info": {
    "issue_date":       { "value": "2023-06-01",  "confidence": 0.85 },
    "examination_name": { "value": "Class XII…",  "confidence": 0.96 }
  },
  "processing_metadata": {
    "model_used": "gemini-1.5-flash",
    "pages_processed": 1,
    "processing_time_ms": 2340.5,
    "file_type": "PDF"
  }
}
```

### Batch extraction

```bash
curl -X POST http://localhost:8000/api/v1/batch \
  -H "Authorization: Bearer <token>" \
  -F "files=@sheet1.pdf" \
  -F "files=@sheet2.png"
```

---

## Running Tests

```bash
pytest tests/ -v
```

Tests use mocked Gemini calls — no real API key required.

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `GEMINI_API_KEY` | **Required.** Google Gemini API key | — |
| `GEMINI_MODEL` | Gemini model identifier | `gemini-1.5-flash` |
| `SECRET_KEY` | JWT signing secret (min 32 chars) | — |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime | `60` |
| `API_USERNAME` | Login username | `admin` |
| `API_PASSWORD` | Login password | `admin123` |
| `MAX_FILE_SIZE_MB` | Upload size limit | `10` |

---

## Project Structure

```
marksheet-extractor/
├── app/
│   ├── main.py            # FastAPI app & all routes
│   ├── auth.py            # JWT utilities & dependency
│   ├── config.py          # Pydantic settings (reads .env)
│   ├── extract.py         # Extraction pipeline orchestrator
│   ├── models.py          # Pydantic request/response schemas
│   └── services/
│       ├── llm_service.py # Google Gemini integration + confidence calibration
│       ├── ocr_service.py # Pillow image preprocessing
│       └── pdf_service.py # PyMuPDF PDF → image conversion
├── tests/
│   ├── conftest.py
│   ├── test_auth.py
│   └── test_extract_api.py
├── frontend/
│   └── index.html         # Drag-and-drop demo UI
├── sample_data/           # Example marksheets for testing
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── APPROACH.md
```

---

## Security Notes

- Credentials are read exclusively from the `.env` file (never hardcoded).
- `.env` is in `.gitignore` and must never be committed.
- Change `API_PASSWORD` and `SECRET_KEY` before any production deployment.
- File type and size are validated before any processing occurs.
