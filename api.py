"""
api.py — FastAPI backend for AI Resume Analyzer
================================================
FIXED version. Changes from original:
  - Checks for "__PDF_ERROR__" prefix in resume_text so parse failures
    surface as user-facing errors rather than silent 0-scores.
  - Returns 503 (not 500) for AI-side failures so the frontend can tell
    infrastructure errors apart from application errors.
  - Component scores (keyword/semantic/format) are exposed in the response
    so you can debug scoring issues without grepping server logs.
  - API key injection via header is logged so you can confirm it's being used.
"""

import os
import logging
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from services.analyzer import analyze_resume

log = logging.getLogger("api")

app = FastAPI(title="AI Resume Analyzer API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalysisRequest(BaseModel):
    resume_text: str = Field(..., max_length=100_000)
    job_description: str = Field(..., max_length=50_000)

    @field_validator("resume_text", "job_description")
    @classmethod
    def sanitize_and_validate(cls, v: str) -> str:
        v_stripped = v.strip()
        if not v_stripped:
            raise ValueError("Value cannot be empty or whitespace only")
        # BUG FIX: surface PDF parse failures as a 400, not a silent 0-score
        if v_stripped.startswith("__PDF_ERROR__:"):
            reason = v_stripped.replace("__PDF_ERROR__:", "")
            raise ValueError(f"PDF parsing failed: {reason}")
        return v_stripped


@app.get("/health")
def health_check():
    """Quick health check — also confirms env var is set (without exposing the key)."""
    return {
        "status": "healthy",
        "openai_key_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
    }


@app.post("/analyze")
def analyze(
    request: AnalysisRequest,
    x_openai_key: str = Header(None, alias="X-OpenAI-Key"),
):
    # ── API key resolution
    # Priority: request header > environment variable
    if x_openai_key and x_openai_key.strip():
        os.environ["OPENAI_API_KEY"] = x_openai_key.strip()
        log.info("Using API key from request header.")
    elif os.environ.get("OPENAI_API_KEY", "").strip():
        log.info("Using API key from environment variable.")
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenAI API key is missing. "
                "Either set the OPENAI_API_KEY environment variable on the server, "
                "or provide it in the X-OpenAI-Key request header."
            ),
        )

    # ── run analysis
    try:
        result = analyze_resume(request.resume_text, request.job_description)
    except Exception as e:
        log.error("Unhandled exception in analyze_resume: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal analysis failure: {type(e).__name__}: {e}",
        )

    # ── BUG FIX B4: check for the error sentinel (-1) and return 503
    if result.get("error") and result.get("score") == -1:
        raise HTTPException(
            status_code=503,
            detail=(
                "Analysis failed on the server side. "
                "Check server logs for the specific error. "
                f"Hint: {result['suggestions'][0] if result.get('suggestions') else 'unknown'}"
            ),
        )

    return result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)