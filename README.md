# ResumeAI — Student Resume Analyzer

ResumeAI is a local full-stack application that compares a resume PDF with a job description. It combines deterministic ATS keyword matching with optional OpenAI semantic scoring and coaching suggestions.

## Features

- Upload a resume PDF up to 5 MB.
- Extract text with `pypdf`, with `pdfminer.six` as a fallback.
- Calculate a weighted score from keyword coverage, semantic relevance, and resume structure.
- Return matched and missing keywords, strengths, and actionable suggestions.
- Provide a responsive Streamlit interface and a FastAPI REST API.
- Keep the API key on the backend and never expose it in the browser.
- Gracefully return rule-based results when the AI service is unavailable.

## Requirements

- Python 3.10 or newer
- Git
- An OpenAI API key for semantic scoring and AI suggestions

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

## Configuration

Create a local environment file named `.env` only if your deployment supports loading it. The application also accepts the key through the `OPENAI_API_KEY` environment variable.

```powershell
$env:OPENAI_API_KEY = "your-api-key"
```

The API supports an `X-OpenAI-Key` request header for local development, but environment configuration is preferred because request headers can be exposed by clients and proxies.

> Never commit a real key. The `.gitignore` excludes `.env` and common secret formats.

## Run locally

Start the API from the repository root:

```powershell
python -m uvicorn api:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, start the web interface:

```powershell
streamlit run app.py
```

Open `http://localhost:8501` in a browser. The frontend calls `http://localhost:8000/analyze`.

## API

### Health check

```http
GET /health
```

### Analyze a resume

```http
POST /analyze
Content-Type: application/json
```

```json
{
  "resume_text": "Python developer with FastAPI experience...",
  "job_description": "Seeking a Python developer with FastAPI and PostgreSQL experience..."
}
```

The response contains the final score, matched and missing keywords, suggestions, strengths, and component scores. A missing API key returns HTTP 400. An AI-side failure returns HTTP 503 when the analyzer reports its explicit fallback error.

## Scoring

- 60% deterministic keyword coverage
- 25% semantic relevance from OpenAI
- 15% resume format completeness

The result is an estimate, not a guarantee. The application uses deterministic fallbacks when AI calls fail so the UI can still display useful guidance.

## Testing

Run the built-in unit and integration tests:

```powershell
python -m unittest discover -s tests -v
```

The tests cover deterministic scoring, PDF text extraction with a generated PDF, API input validation, and the health endpoint.

## Project structure

```text
.
├── api.py                 # FastAPI REST API
├── app.py                 # Streamlit user interface
├── services/
│   └── analyzer.py        # Keyword, semantic, and format analysis
├── utils/
│   └── pdf_parser.py      # PDF extraction
├── tests/                 # Automated tests
├── requirements.txt        # Runtime dependencies
└── README.md
```

## Troubleshooting

- If the frontend cannot reach the API, confirm the API is running on port 8000.
- If the API reports that the key is missing, set `OPENAI_API_KEY` and restart the API.
- If a PDF produces no text, it may be image-only. Use a text-based PDF or OCR before uploading it.
- If OpenAI requests fail or rate limit, the analyzer uses rule-based fallbacks and returns a warning in the server logs.
- Use `LOG_LEVEL=DEBUG` only for local troubleshooting because prompts and responses can contain resume data.

## License

This project is provided for local use and may be adapted for your own resume-analysis workflow.
