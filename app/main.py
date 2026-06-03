import asyncio
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import List

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

from google.api_core import exceptions as google_exceptions

from app.auth import authenticate_user, create_access_token, get_current_user
from app.config import Settings, get_settings
from app.extract import extract_marksheet
from app.models import (
    BatchExtractionResponse,
    BatchItemResult,
    ExtractionResponse,
    TokenResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_retry_after(exc: google_exceptions.ResourceExhausted) -> int:
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", str(exc), re.IGNORECASE)
    return int(float(match.group(1))) + 1 if match else 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    logger.info("Marksheet Extractor API starting up …")
    yield
    logger.info("Marksheet Extractor API shutting down.")


app = FastAPI(
    title="Marksheet Extractor",
    description=(
        "Extract candidate details, subject marks, and results from academic "
        "marksheets (JPG/PNG/PDF).\n\n"
        "**Auth:** POST `/auth/token` with form credentials to get a Bearer token."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"], summary="Root health check")
async def root():
    return {"status": "ok", "message": "Marksheet Extractor API", "version": "1.0.0"}


@app.get("/health", tags=["Health"], summary="Liveness probe")
async def health():
    return {"status": "healthy"}


@app.post(
    "/auth/token",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Obtain a JWT access token",
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
):
    """Submit `username` and `password` (form-encoded) to receive a Bearer token."""
    if not authenticate_user(form_data.username, form_data.password, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(
        data={"sub": form_data.username},
        settings=settings,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@app.post(
    "/api/v1/extract",
    response_model=ExtractionResponse,
    tags=["Extraction"],
    summary="Extract data from a single marksheet",
    status_code=200,
)
async def extract_single(
    file: UploadFile = File(..., description="Marksheet - JPG, PNG, or PDF (max 10 MB)"),
    _: str = Depends(get_current_user),
):
    """Upload a marksheet image or PDF; returns structured extraction results."""
    content = await file.read()
    filename = file.filename or "upload"

    try:
        return await extract_marksheet(file_bytes=content, filename=filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except google_exceptions.ResourceExhausted as exc:
        retry_after = _parse_retry_after(exc)
        logger.warning("Gemini quota exhausted for '%s', retry after %ss", filename, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Gemini API quota exceeded. Please wait and retry.",
            headers={"Retry-After": str(retry_after)},
        ) from exc
    except Exception as exc:
        logger.exception("Extraction failed for '%s'", filename)
        raise HTTPException(
            status_code=500,
            detail="Internal extraction error. Please try again.",
        ) from exc


@app.post(
    "/api/v1/batch",
    response_model=BatchExtractionResponse,
    tags=["Extraction"],
    summary="Extract data from multiple marksheets concurrently (max 10)",
    status_code=200,
)
async def extract_batch(
    files: List[UploadFile] = File(..., description="Up to 10 marksheet files"),
    _: str = Depends(get_current_user),
):
    """Process up to 10 marksheets in parallel. A failure in one file does not stop the rest."""
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 files per batch request.")
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided.")

    batch_id = str(uuid.uuid4())

    async def _process_one(upload: UploadFile) -> BatchItemResult:
        fname = upload.filename or "upload"
        try:
            content = await upload.read()
            result = await extract_marksheet(file_bytes=content, filename=fname)
            return BatchItemResult(filename=fname, status="success", data=result)
        except ValueError as exc:
            return BatchItemResult(filename=fname, status="failed", error=str(exc))
        except google_exceptions.ResourceExhausted as exc:
            logger.warning("Gemini quota exhausted for batch item '%s'", fname)
            return BatchItemResult(filename=fname, status="failed", error="Gemini API quota exceeded. Please retry later.")
        except Exception as exc:
            logger.exception("Batch item failed: '%s'", fname)
            return BatchItemResult(filename=fname, status="failed", error="Processing error")

    results: List[BatchItemResult] = await asyncio.gather(
        *[_process_one(f) for f in files]
    )

    successful = sum(1 for r in results if r.status == "success")
    return BatchExtractionResponse(
        batch_id=batch_id,
        total_files=len(files),
        successful=successful,
        failed=len(files) - successful,
        results=results,
    )


@app.get(
    "/demo",
    response_class=HTMLResponse,
    tags=["Demo"],
    include_in_schema=False,
)
async def demo_page():
    html_path = Path("frontend/index.html")
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h2>Demo page not found. Place frontend/index.html in the project root.</h2>",
        status_code=404,
    )
