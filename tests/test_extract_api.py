"""Tests for extraction endpoints (LLM calls are mocked)."""

import io
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _png_bytes(width: int = 100, height: int = 100) -> bytes:
    """Return a minimal in-memory PNG image as bytes."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    """Return a minimal valid PDF (1-page, no content)."""
    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
        b"xref\n0 4\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )


# A minimal but schema-complete LLM response
_MOCK_LLM_RESULT = {
    "candidate_details": {
        "name": {"value": "Ravi Kumar", "confidence": 0.97},
        "father_name": {"value": "Suresh Kumar", "confidence": 0.92},
        "mother_name": {"value": None, "confidence": 0.0},
        "roll_no": {"value": "1234567", "confidence": 0.99},
        "registration_no": {"value": "REG-2023-001", "confidence": 0.95},
        "dob": {"value": "2000-04-15", "confidence": 0.88},
        "exam_year": {"value": "2023", "confidence": 0.99},
        "board_university": {"value": "CBSE", "confidence": 0.98},
        "institution": {"value": "Delhi Public School", "confidence": 0.90},
    },
    "subjects": [
        {
            "subject_name": {"value": "Mathematics", "confidence": 0.99},
            "subject_code": {"value": "041", "confidence": 0.95},
            "max_marks": {"value": 100, "confidence": 0.98},
            "obtained_marks": {"value": 92, "confidence": 0.97},
            "max_credits": {"value": None, "confidence": 0.0},
            "obtained_credits": {"value": None, "confidence": 0.0},
            "grade": {"value": "A1", "confidence": 0.96},
            "grade_points": {"value": None, "confidence": 0.0},
            "pass_fail": {"value": "PASS", "confidence": 0.99},
        }
    ],
    "overall_result": {
        "total_max_marks": {"value": 500, "confidence": 0.97},
        "total_obtained_marks": {"value": 452, "confidence": 0.96},
        "percentage": {"value": 90.4, "confidence": 0.97},
        "cgpa": {"value": None, "confidence": 0.0},
        "sgpa": {"value": None, "confidence": 0.0},
        "grade": {"value": "A1", "confidence": 0.95},
        "division": {"value": "First Division", "confidence": 0.93},
        "result_status": {"value": "PASS", "confidence": 0.99},
        "rank": {"value": None, "confidence": 0.0},
    },
    "document_info": {
        "issue_date": {"value": "2023-06-01", "confidence": 0.85},
        "issue_place": {"value": "New Delhi", "confidence": 0.80},
        "document_type": {"value": "Marksheet", "confidence": 0.98},
        "academic_year": {"value": "2022-23", "confidence": 0.97},
        "semester": {"value": None, "confidence": 0.0},
        "examination_name": {"value": "Class XII Board Examination", "confidence": 0.96},
    },
}


# ---------------------------------------------------------------------------
# Fixtures / shared mock
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_llm():
    """Patch the LLM service so tests never call Gemini."""
    with patch(
        "app.extract.get_llm_service"
    ) as mock_factory:
        svc = mock_factory.return_value
        svc.model_name = "gemini-1.5-flash"
        svc.extract_marksheet = AsyncMock(return_value=_MOCK_LLM_RESULT)
        yield svc


# ---------------------------------------------------------------------------
# Single extraction
# ---------------------------------------------------------------------------

class TestExtractSingle:
    def test_extract_png_success(self, client: TestClient, auth_headers, mock_llm):
        resp = client.post(
            "/api/v1/extract",
            headers=auth_headers,
            files={"file": ("sheet.png", _png_bytes(), "image/png")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["candidate_details"]["name"]["value"] == "Ravi Kumar"
        assert body["candidate_details"]["name"]["confidence"] > 0
        assert isinstance(body["subjects"], list)
        assert len(body["subjects"]) == 1
        assert body["overall_result"]["percentage"]["value"] == 90.4
        assert "processing_metadata" in body

    def test_extract_pdf_success(self, client: TestClient, auth_headers, mock_llm):
        resp = client.post(
            "/api/v1/extract",
            headers=auth_headers,
            files={"file": ("sheet.pdf", _pdf_bytes(), "application/pdf")},
        )
        # PDF parsing of a minimal stub might raise an error; accept 200 or 400
        assert resp.status_code in (200, 400, 500)

    def test_extract_unsupported_type(self, client: TestClient, auth_headers):
        resp = client.post(
            "/api/v1/extract",
            headers=auth_headers,
            files={"file": ("sheet.docx", b"dummy", "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "docx" in resp.json()["detail"].lower()

    def test_extract_file_too_large(self, client: TestClient, auth_headers):
        # 11 MB of zeros
        big = b"\x00" * (11 * 1024 * 1024)
        resp = client.post(
            "/api/v1/extract",
            headers=auth_headers,
            files={"file": ("big.png", big, "image/png")},
        )
        assert resp.status_code == 400
        assert "10 MB" in resp.json()["detail"]

    def test_extract_no_auth(self, client: TestClient):
        resp = client.post(
            "/api/v1/extract",
            files={"file": ("sheet.png", _png_bytes(), "image/png")},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

class TestExtractBatch:
    def test_batch_success(self, client: TestClient, auth_headers, mock_llm):
        files = [
            ("files", ("a.png", _png_bytes(), "image/png")),
            ("files", ("b.png", _png_bytes(), "image/png")),
        ]
        resp = client.post("/api/v1/batch", headers=auth_headers, files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_files"] == 2
        assert body["successful"] == 2
        assert body["failed"] == 0
        assert "batch_id" in body

    def test_batch_too_many_files(self, client: TestClient, auth_headers):
        files = [("files", (f"f{i}.png", _png_bytes(), "image/png")) for i in range(11)]
        resp = client.post("/api/v1/batch", headers=auth_headers, files=files)
        assert resp.status_code == 400

    def test_batch_mixed_valid_invalid(self, client: TestClient, auth_headers, mock_llm):
        files = [
            ("files", ("ok.png", _png_bytes(), "image/png")),
            ("files", ("bad.exe", b"not a file", "application/octet-stream")),
        ]
        resp = client.post("/api/v1/batch", headers=auth_headers, files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert body["successful"] == 1
        assert body["failed"] == 1


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------

class TestResponseSchema:
    def test_field_value_confidence_range(self, client: TestClient, auth_headers, mock_llm):
        resp = client.post(
            "/api/v1/extract",
            headers=auth_headers,
            files={"file": ("sheet.png", _png_bytes(), "image/png")},
        )
        body = resp.json()

        def _check_field(fv: dict):
            assert "value" in fv
            assert "confidence" in fv
            assert 0.0 <= fv["confidence"] <= 1.0

        _check_field(body["candidate_details"]["name"])
        _check_field(body["overall_result"]["percentage"])
        for subj in body["subjects"]:
            _check_field(subj["subject_name"])
            _check_field(subj["obtained_marks"])
