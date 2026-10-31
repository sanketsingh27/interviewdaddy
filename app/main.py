from __future__ import annotations

import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError


ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.environ.get("INTERVIEWDADDY_DATABASE", ROOT / "data" / "preparations.sqlite3"))
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_RESUME_CHARACTERS = 100_000
EXPERIENCE_LEVELS = {"entry", "early-career", "mid-level", "senior", "staff"}

app = FastAPI(title="InterviewDaddy", docs_url=None, redoc_url=None)


def connect_database() -> sqlite3.Connection:
    """Open a SQLite connection with row access and foreign keys enabled."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    """Create preparation and interview tables, including additive interview migrations."""
    with connect_database() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS preparations (
                id TEXT PRIMARY KEY,
                target_role TEXT NOT NULL,
                experience_level TEXT NOT NULL,
                job_description TEXT NOT NULL,
                resume_text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS interviews (
                id TEXT PRIMARY KEY,
                preparation_id TEXT NOT NULL REFERENCES preparations(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
                question TEXT NOT NULL,
                turns TEXT NOT NULL,
                started_at TEXT NOT NULL,
                follow_ups_used INTEGER NOT NULL DEFAULT 0,
                processing INTEGER NOT NULL DEFAULT 0
            )"""
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(interviews)")}
        if "processing" not in columns:
            connection.execute("ALTER TABLE interviews ADD COLUMN processing INTEGER NOT NULL DEFAULT 0")
        if "paused_at" not in columns:
            connection.execute("ALTER TABLE interviews ADD COLUMN paused_at TEXT")
            connection.execute("ALTER TABLE interviews ADD COLUMN paused_seconds REAL NOT NULL DEFAULT 0")

@app.post("/api/interviews/{interview_id}/pause")
def pause_interview(interview_id: str) -> dict:
    from app.interview import set_paused
    return set_paused(interview_id, True)

@app.post("/api/interviews/{interview_id}/resume")
def resume_interview(interview_id: str) -> dict:
    from app.interview import set_paused
    return set_paused(interview_id, False)

class InterviewStartInput(BaseModel):
    preparation_id: str


class InterviewAnswerInput(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class InterviewActionInput(BaseModel):
    action: str


@app.post("/api/interviews/{interview_id}/actions")
def interview_action(interview_id: str, payload: InterviewActionInput) -> dict:
    from app.interview import handle_action

    return handle_action(interview_id, payload.action)


@app.post("/api/interviews", status_code=201)
def start_interview(payload: InterviewStartInput) -> dict:
    from app.interview import create_interview

    return create_interview(payload.preparation_id)


@app.get("/api/interviews/{interview_id}")
def read_interview(interview_id: str) -> dict:
    from app.interview import get_interview

    return get_interview(interview_id)


@app.post("/api/interviews/{interview_id}/turns")
def add_interview_turn(interview_id: str, payload: InterviewAnswerInput) -> dict:
    from app.interview import submit_answer

    return submit_answer(interview_id, payload.text)


@app.post("/api/interviews/{interview_id}/finish")
def end_interview(interview_id: str) -> dict:
    from app.interview import finish_interview

    return finish_interview(interview_id)


@app.on_event("startup")
def startup() -> None:
    """Initialize persistent storage when the application starts."""
    initialize_database()


class PreparationInput(BaseModel):
    target_role: str = Field(min_length=1, max_length=120)
    experience_level: str
    job_description: str = Field(default="", max_length=30_000)
    resume_text: str = Field(min_length=1, max_length=100_000)


def preparation_to_dict(row: sqlite3.Row) -> dict[str, str]:
    """Convert a preparation database row into its API representation."""
    return {
        "id": row["id"],
        "target_role": row["target_role"],
        "experience_level": row["experience_level"],
        "job_description": row["job_description"],
        "resume_text": row["resume_text"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def validate_preparation(preparation: PreparationInput) -> PreparationInput:
    """Trim and validate preparation fields before database operations."""
    target_role = preparation.target_role.strip()
    resume_text = preparation.resume_text.strip()
    if not target_role:
        raise HTTPException(status_code=422, detail="Enter a target role before saving.")
    if not resume_text:
        raise HTTPException(status_code=422, detail="Resume text cannot be blank.")
    if preparation.experience_level not in EXPERIENCE_LEVELS:
        raise HTTPException(status_code=422, detail="Choose a valid experience level.")
    return PreparationInput(
        target_role=target_role,
        experience_level=preparation.experience_level,
        job_description=preparation.job_description.strip(),
        resume_text=resume_text,
    )


@app.get("/")
def index() -> FileResponse:
    """Serve the application homepage."""
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/extract")
async def extract_resume(file: UploadFile = File(...)) -> dict[str, str]:
    """Extract readable text from an uploaded PDF resume."""
    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf") or file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Choose a PDF file to extract resume text.")

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="This PDF is larger than 8 MB. Choose a smaller file.")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="This file does not have a valid PDF header. Choose another PDF.")

    try:
        reader = PdfReader(io.BytesIO(contents), strict=True)
        if reader.is_encrypted:
            raise HTTPException(
                status_code=400,
                detail="This PDF is password-protected. Export an unlocked copy and try again.",
            )
        pages = [page.extract_text() or "" for page in reader.pages]
    except HTTPException:
        raise
    except (PdfReadError, ValueError, OSError, KeyError, IndexError) as error:
        raise HTTPException(
            status_code=400,
            detail="We could not read this PDF. Try exporting it again as a standard PDF.",
        ) from error

    extracted_text = "\n\n".join(page.strip() for page in pages if page.strip()).strip()
    if not extracted_text:
        raise HTTPException(
            status_code=422,
            detail="No readable text was found. This may be a scanned PDF; OCR is not supported, so use a text-based PDF.",
        )
    if len(extracted_text) > MAX_RESUME_CHARACTERS:
        raise HTTPException(
            status_code=413,
            detail="The extracted text is longer than 100,000 characters. Try a shorter resume PDF.",
        )

    # Extracted resume contents are untrusted user data and are never treated as instructions.
    return {"resume_text": extracted_text}


@app.get("/api/preparations")
def list_preparations() -> list[dict[str, str]]:
    """Return saved preparations ordered by most recently updated."""
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT id, target_role, experience_level, updated_at FROM preparations ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/preparations", status_code=201)
def save_preparation(preparation: PreparationInput) -> dict[str, str]:
    """Validate and store a new preparation, then return its saved data."""
    preparation = validate_preparation(preparation)
    preparation_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    with connect_database() as connection:
        connection.execute(
            """INSERT INTO preparations
            (id, target_role, experience_level, job_description, resume_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                preparation_id,
                preparation.target_role,
                preparation.experience_level,
                preparation.job_description,
                preparation.resume_text,
                timestamp,
                timestamp,
            ),
        )
        row = connection.execute("SELECT * FROM preparations WHERE id = ?", (preparation_id,)).fetchone()
    return preparation_to_dict(row)


@app.put("/api/preparations/{preparation_id}")
def update_preparation(preparation_id: str, preparation: PreparationInput) -> dict[str, str]:
    """Update a saved preparation or raise 404 if it does not exist."""
    preparation = validate_preparation(preparation)
    timestamp = datetime.now(timezone.utc).isoformat()
    with connect_database() as connection:
        cursor = connection.execute(
            """UPDATE preparations SET target_role = ?, experience_level = ?, job_description = ?,
            resume_text = ?, updated_at = ? WHERE id = ?""",
            (
                preparation.target_role,
                preparation.experience_level,
                preparation.job_description,
                preparation.resume_text,
                timestamp,
                preparation_id,
            ),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="This preparation was not found. It may have been deleted.")
        row = connection.execute("SELECT * FROM preparations WHERE id = ?", (preparation_id,)).fetchone()
    return preparation_to_dict(row)


@app.get("/api/preparations/{preparation_id}")
def get_preparation(preparation_id: str) -> dict[str, str]:
    """Return one saved preparation or raise 404 if it does not exist."""
    with connect_database() as connection:
        row = connection.execute("SELECT * FROM preparations WHERE id = ?", (preparation_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="This preparation was not found. It may have been deleted.")
    return preparation_to_dict(row)


@app.delete("/api/preparations/{preparation_id}", status_code=204)
def delete_preparation(preparation_id: str) -> None:
    """Delete a saved preparation or raise 404 if it does not exist."""
    with connect_database() as connection:
        cursor = connection.execute("DELETE FROM preparations WHERE id = ?", (preparation_id,))
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="This preparation was not found. It may have been deleted.")
