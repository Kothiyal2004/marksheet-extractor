from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class FieldValue(BaseModel):
    value: Optional[Any] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score 0-1")

class CandidateDetails(BaseModel):
    name: FieldValue
    father_name: FieldValue
    mother_name: FieldValue
    roll_no: FieldValue
    registration_no: FieldValue
    dob: FieldValue = Field(description="Date of birth (ISO YYYY-MM-DD when available)")
    exam_year: FieldValue
    board_university: FieldValue
    institution: FieldValue


class SubjectMarks(BaseModel):
    subject_name: FieldValue
    subject_code: FieldValue
    max_marks: FieldValue
    obtained_marks: FieldValue
    max_credits: FieldValue
    obtained_credits: FieldValue
    grade: FieldValue
    grade_points: FieldValue
    pass_fail: FieldValue


class OverallResult(BaseModel):
    total_max_marks: FieldValue
    total_obtained_marks: FieldValue
    percentage: FieldValue
    cgpa: FieldValue
    sgpa: FieldValue
    grade: FieldValue
    division: FieldValue
    result_status: FieldValue
    rank: FieldValue


class DocumentInfo(BaseModel):
    issue_date: FieldValue
    issue_place: FieldValue
    document_type: FieldValue
    academic_year: FieldValue
    semester: FieldValue
    examination_name: FieldValue


# metadata added by the API itself (not extracted from the document)
class ProcessingMetadata(BaseModel):
    model_config = {"protected_namespaces": ()}

    model_used: str
    pages_processed: int
    processing_time_ms: float
    file_type: str
    file_name: str
    file_size_bytes: int


class ExtractionResponse(BaseModel):
    document_id: str
    processed_at: datetime
    candidate_details: CandidateDetails
    subjects: List[SubjectMarks]
    overall_result: OverallResult
    document_info: DocumentInfo
    processing_metadata: ProcessingMetadata


class BatchItemResult(BaseModel):
    filename: str
    status: str  # "success" | "failed"
    data: Optional[ExtractionResponse] = None
    error: Optional[str] = None


class BatchExtractionResponse(BaseModel):
    batch_id: str
    total_files: int
    successful: int
    failed: int
    results: List[BatchItemResult]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token lifetime in seconds")
