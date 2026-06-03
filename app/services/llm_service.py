import asyncio
import json
import logging
import re
import time
from typing import List

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from PIL import Image

from app.config import get_settings

logger = logging.getLogger(__name__)

# Using gemini-1.5-flash: fast and handles multi-image input well.
# JSON mode (response_mime_type) saves us from parsing markdown fences.
# temperature=0.1 keeps extraction answers deterministic.

_EXTRACTION_PROMPT = """\
You are an expert academic document analyst familiar with marksheets, transcripts,
and report cards from CBSE, ICSE, state boards, IIT/NIT semester systems,
credit-based grading, and international formats.

Analyse ALL provided images (they may be multiple pages of the same document)
and extract every piece of information you can find.

CONFIDENCE SCORING (0.0 to 1.0 per field):
  Combine three factors:
  - Visibility (35%): how clearly is the text readable?
  - Certainty  (40%): how confident are you in the extracted value?
  - Consistency (25%): does it make sense in context?

  Use value=null and confidence=0.0 for absent or unreadable fields.

EXTRACTION RULES:
1. Extract exactly what is written. Do not guess or infer.
2. Dates should be ISO format YYYY-MM-DD where possible; otherwise keep original.
3. Marks, credits, grade points must be numeric (int or float), not strings.
4. Percentage must be a numeric float (e.g. 85.4, not "85.4%").
5. The subjects array must include EVERY subject row visible.
6. Use null (not empty string) for absent or unreadable fields.

Return ONLY the following JSON structure, nothing else:
{
  "candidate_details": {
    "name":            {"value": null, "confidence": 0.0},
    "father_name":     {"value": null, "confidence": 0.0},
    "mother_name":     {"value": null, "confidence": 0.0},
    "roll_no":         {"value": null, "confidence": 0.0},
    "registration_no": {"value": null, "confidence": 0.0},
    "dob":             {"value": null, "confidence": 0.0},
    "exam_year":       {"value": null, "confidence": 0.0},
    "board_university":{"value": null, "confidence": 0.0},
    "institution":     {"value": null, "confidence": 0.0}
  },
  "subjects": [
    {
      "subject_name":    {"value": null, "confidence": 0.0},
      "subject_code":    {"value": null, "confidence": 0.0},
      "max_marks":       {"value": null, "confidence": 0.0},
      "obtained_marks":  {"value": null, "confidence": 0.0},
      "max_credits":     {"value": null, "confidence": 0.0},
      "obtained_credits":{"value": null, "confidence": 0.0},
      "grade":           {"value": null, "confidence": 0.0},
      "grade_points":    {"value": null, "confidence": 0.0},
      "pass_fail":       {"value": null, "confidence": 0.0}
    }
  ],
  "overall_result": {
    "total_max_marks":      {"value": null, "confidence": 0.0},
    "total_obtained_marks": {"value": null, "confidence": 0.0},
    "percentage":           {"value": null, "confidence": 0.0},
    "cgpa":                 {"value": null, "confidence": 0.0},
    "sgpa":                 {"value": null, "confidence": 0.0},
    "grade":                {"value": null, "confidence": 0.0},
    "division":             {"value": null, "confidence": 0.0},
    "result_status":        {"value": null, "confidence": 0.0},
    "rank":                 {"value": null, "confidence": 0.0}
  },
  "document_info": {
    "issue_date":       {"value": null, "confidence": 0.0},
    "issue_place":      {"value": null, "confidence": 0.0},
    "document_type":    {"value": null, "confidence": 0.0},
    "academic_year":    {"value": null, "confidence": 0.0},
    "semester":         {"value": null, "confidence": 0.0},
    "examination_name": {"value": null, "confidence": 0.0}
  }
}
"""


def _format_score(value, field_type: str) -> float:
    """Simple heuristic: does the value look plausible for this field type?"""
    if value is None:
        return 0.0
    s = str(value).strip()
    if not s:
        return 0.0

    if field_type == "dob":
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return 1.0
        if re.search(r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}", s):
            return 0.7
        return 0.4

    if field_type == "percentage":
        try:
            v = float(s.replace("%", ""))
            return 1.0 if 0 <= v <= 100 else 0.2
        except ValueError:
            return 0.3

    if field_type == "marks":
        try:
            v = float(s)
            return 1.0 if v >= 0 else 0.1
        except (ValueError, TypeError):
            return 0.3

    if field_type == "year":
        if re.fullmatch(r"\d{4}", s):
            return 1.0 if 1950 <= int(s) <= 2035 else 0.3
        return 0.4

    if field_type == "name":
        return 1.0 if len(s) >= 2 else 0.3

    return 1.0


def _calibrate(llm_conf: float, value, field_type: str = "generic") -> float:
    # blend LLM self-reported confidence (70%) with our format check (30%)
    fs = _format_score(value, field_type)
    return round(min(1.0, max(0.0, 0.70 * llm_conf + 0.30 * fs)), 3)


_CANDIDATE_FIELD_TYPES = {
    "name": "name",
    "father_name": "name",
    "mother_name": "name",
    "dob": "dob",
    "exam_year": "year",
}

_SUBJECT_NUMERIC_FIELDS = {
    "max_marks", "obtained_marks", "max_credits", "obtained_credits", "grade_points"
}


def _apply_calibration(extracted: dict) -> dict:
    for field, fd in extracted.get("candidate_details", {}).items():
        if isinstance(fd, dict):
            ftype = _CANDIDATE_FIELD_TYPES.get(field, "generic")
            fd["confidence"] = _calibrate(fd.get("confidence", 0.0), fd.get("value"), ftype)

    for subj in extracted.get("subjects", []):
        for field, fd in subj.items():
            if isinstance(fd, dict):
                ftype = "marks" if field in _SUBJECT_NUMERIC_FIELDS else "generic"
                fd["confidence"] = _calibrate(fd.get("confidence", 0.0), fd.get("value"), ftype)

    for field, fd in extracted.get("overall_result", {}).items():
        if isinstance(fd, dict):
            if field == "percentage":
                ftype = "percentage"
            elif field in {"total_max_marks", "total_obtained_marks"}:
                ftype = "marks"
            else:
                ftype = "generic"
            fd["confidence"] = _calibrate(fd.get("confidence", 0.0), fd.get("value"), ftype)

    for _, fd in extracted.get("document_info", {}).items():
        if isinstance(fd, dict):
            fd["confidence"] = _calibrate(fd.get("confidence", 0.0), fd.get("value"), "generic")

    return extracted


class GeminiLLMService:
    def __init__(self) -> None:
        settings = get_settings()
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self._generation_config = genai.GenerationConfig(
            temperature=0.1,
            max_output_tokens=8192,
            response_mime_type="application/json",
        )
        self._model = genai.GenerativeModel(
            model_name=settings.GEMINI_MODEL,
            generation_config=self._generation_config,
        )
        self.model_name: str = settings.GEMINI_MODEL

    def _call_gemini(self, content_parts: list, *, max_retries: int = 3) -> str:
        delay = 60.0
        for attempt in range(max_retries):
            try:
                response = self._model.generate_content(content_parts)
                return response.text
            except google_exceptions.ResourceExhausted as exc:
                if attempt == max_retries - 1:
                    raise
                # Parse suggested retry delay from the error message if present
                m = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc))
                delay = float(m.group(1)) if m else delay
                logger.warning(
                    "Gemini quota exhausted (attempt %d/%d). Retrying in %.0fs …",
                    attempt + 1, max_retries, delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 300)  # cap at 5 minutes

    async def extract_marksheet(self, images: List[Image.Image]) -> dict:
        content_parts: list = [_EXTRACTION_PROMPT]

        if len(images) > 1:
            content_parts.append(
                f"\nNote: The following {len(images)} images are consecutive pages "
                "of the same document. Treat them as one marksheet.\n"
            )

        content_parts.extend(images)

        # SDK call is synchronous, so push it off the event loop
        raw_text: str = await asyncio.to_thread(self._call_gemini, content_parts)

        try:
            extracted: dict = json.loads(raw_text)
        except json.JSONDecodeError:
            # JSON mode should prevent this, but just in case
            start, end = raw_text.find("{"), raw_text.rfind("}") + 1
            if start == -1 or end == 0:
                raise ValueError("LLM returned a non-JSON response")
            extracted = json.loads(raw_text[start:end])

        return _apply_calibration(extracted)


# lazy singleton - created on first request
_service: GeminiLLMService | None = None


def get_llm_service() -> GeminiLLMService:
    global _service
    if _service is None:
        _service = GeminiLLMService()
    return _service
