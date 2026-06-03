import logging
import time
import uuid
from datetime import datetime, timezone
from typing import List

from PIL import Image

from app.models import (
    CandidateDetails,
    DocumentInfo,
    ExtractionResponse,
    FieldValue,
    OverallResult,
    ProcessingMetadata,
    SubjectMarks,
)
from app.services.llm_service import get_llm_service
from app.services.ocr_service import load_image_from_bytes, preprocess_image
from app.services.pdf_service import pdf_to_images

logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
_MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB


def _extension(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_file(filename: str, file_size: int) -> str:
    """Return 'pdf' or 'image' after checking extension and size."""
    ext = _extension(filename)
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file extension '.{ext}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
        )
    if file_size >= _MAX_FILE_BYTES:
        raise ValueError(
            f"File size {file_size / 1_048_576:.1f} MB exceeds the 10 MB limit."
        )
    return "pdf" if ext == "pdf" else "image"


def _fv(raw: object) -> FieldValue:
    """Wrap a raw LLM field dict in a FieldValue, with safe defaults."""
    if not isinstance(raw, dict):
        return FieldValue(value=None, confidence=0.0)
    return FieldValue(
        value=raw.get("value"),
        confidence=float(max(0.0, min(1.0, raw.get("confidence", 0.0)))),
    )


def _build_response(extracted: dict, metadata: ProcessingMetadata) -> ExtractionResponse:
    cd = extracted.get("candidate_details", {})
    candidate = CandidateDetails(
        name=_fv(cd.get("name")),
        father_name=_fv(cd.get("father_name")),
        mother_name=_fv(cd.get("mother_name")),
        roll_no=_fv(cd.get("roll_no")),
        registration_no=_fv(cd.get("registration_no")),
        dob=_fv(cd.get("dob")),
        exam_year=_fv(cd.get("exam_year")),
        board_university=_fv(cd.get("board_university")),
        institution=_fv(cd.get("institution")),
    )

    subjects: List[SubjectMarks] = []
    for s in extracted.get("subjects", []):
        subjects.append(
            SubjectMarks(
                subject_name=_fv(s.get("subject_name")),
                subject_code=_fv(s.get("subject_code")),
                max_marks=_fv(s.get("max_marks")),
                obtained_marks=_fv(s.get("obtained_marks")),
                max_credits=_fv(s.get("max_credits")),
                obtained_credits=_fv(s.get("obtained_credits")),
                grade=_fv(s.get("grade")),
                grade_points=_fv(s.get("grade_points")),
                pass_fail=_fv(s.get("pass_fail")),
            )
        )

    ov = extracted.get("overall_result", {})
    overall = OverallResult(
        total_max_marks=_fv(ov.get("total_max_marks")),
        total_obtained_marks=_fv(ov.get("total_obtained_marks")),
        percentage=_fv(ov.get("percentage")),
        cgpa=_fv(ov.get("cgpa")),
        sgpa=_fv(ov.get("sgpa")),
        grade=_fv(ov.get("grade")),
        division=_fv(ov.get("division")),
        result_status=_fv(ov.get("result_status")),
        rank=_fv(ov.get("rank")),
    )

    di = extracted.get("document_info", {})
    doc_info = DocumentInfo(
        issue_date=_fv(di.get("issue_date")),
        issue_place=_fv(di.get("issue_place")),
        document_type=_fv(di.get("document_type")),
        academic_year=_fv(di.get("academic_year")),
        semester=_fv(di.get("semester")),
        examination_name=_fv(di.get("examination_name")),
    )

    stem = metadata.file_name.rsplit(".", 1)[0]
    doc_id = f"{stem}-{uuid.uuid4().hex[:8]}"

    return ExtractionResponse(
        document_id=doc_id,
        processed_at=datetime.now(timezone.utc),
        candidate_details=candidate,
        subjects=subjects,
        overall_result=overall,
        document_info=doc_info,
        processing_metadata=metadata,
    )


async def extract_marksheet(
    file_bytes: bytes,
    filename: str,
) -> ExtractionResponse:
    """Run the full pipeline: validate → decode → preprocess → LLM → assemble."""
    t0 = time.perf_counter()
    file_size = len(file_bytes)
    file_type = validate_file(filename, file_size)

    if file_type == "pdf":
        images: List[Image.Image] = pdf_to_images(file_bytes)
    else:
        images = [load_image_from_bytes(file_bytes)]

    images = [preprocess_image(img) for img in images]

    llm = get_llm_service()
    extracted = await llm.extract_marksheet(images)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    metadata = ProcessingMetadata(
        model_used=llm.model_name,
        pages_processed=len(images),
        processing_time_ms=elapsed_ms,
        file_type=file_type.upper(),
        file_name=filename,
        file_size_bytes=file_size,
    )
    return _build_response(extracted, metadata)
