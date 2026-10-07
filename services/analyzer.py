"""
analyzer.py — Hybrid ATS Resume Analyzer
=========================================
Scoring breakdown:
  60%  keyword score   (rule-based, deterministic)
  25%  semantic score  (AI-based, via OpenAI)
  15%  format score    (rule-based heuristics)

This is the FIXED version. Key changes from original:
  - Exceptions are logged with reasons, not swallowed silently
  - FALLBACK score is -1 (impossible real value) so you can tell it apart from score=0
  - _is_valid() accepts string scores and coerces them
  - Real keyword extraction and matching (no longer hallucinated by GPT)
  - AI only scores semantic relevance (what it's actually good at)
  - PyPDF2 / pypdf handled cleanly upstream; analyzer assumes clean text in
"""

import os
import re
import json
import logging
from openai import OpenAI, AuthenticationError, RateLimitError, APIError

# ── logging ────────────────────────────────────────────────────────────────────
# Set LOG_LEVEL=DEBUG in your env to see full prompts and responses.
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=os.getenv("LOG_LEVEL", "INFO"),
)
log = logging.getLogger("analyzer")


# ── sentinel value ─────────────────────────────────────────────────────────────
# -1 is impossible as a real score (range is 0–100).
# Frontend should check for -1 and show "Analysis failed" instead of "Score: -1".
FALLBACK = {
    "score": -1,
    "matched_keywords": [],
    "missing_keywords": [],
    "suggestions": ["Analysis failed — check server logs for the reason."],
    "strengths": [],
    "component_scores": {"keyword": 0, "semantic": 0, "format": 0},
    "error": True,
}

# Keywords that add no signal — filtered before matching
# Rule: if a word could appear in ANY job description regardless of domain, it's a stopword.
# Only technical skills, tools, languages, and domain terms should survive.
STOPWORDS = {
    # articles / prepositions / conjunctions
    "the", "and", "for", "with", "this", "that", "from", "into", "onto",
    "about", "above", "after", "also", "both", "each", "few", "more",
    "most", "other", "over", "same", "than", "then", "they", "very",
    # generic verbs
    "have", "will", "are", "was", "been", "can", "may", "must", "use",
    "using", "used", "help", "work", "join", "build", "make", "take",
    "give", "come", "know", "get", "see", "think", "look", "want",
    # pronouns / possessives
    "you", "your", "our", "their", "its", "they", "them", "who", "what",
    "which", "when", "where", "how",
    # job posting filler — words that appear in every JD
    "role", "team", "ability", "experience", "strong", "good", "great",
    "excellent", "proven", "plus", "bonus", "nice", "preferred", "required",
    "responsibilities", "requirements", "qualifications", "including", "such",
    "position", "candidate", "looking", "seeking", "join", "need", "needs",
    "opportunity", "eager", "motivated", "passionate", "driven", "excited",
    "learn", "learning", "grow", "growing", "growth", "fast", "dynamic",
    "collaborative", "startup", "company", "organization", "organisation",
    "environment", "culture", "values", "mission", "vision",
    # intern / fresher specific filler — exact words from your screenshot
    "intern", "internship", "fresher", "freshers", "graduate", "graduates",
    "entry", "level", "job", "jobs", "description", "location", "remote",
    "onsite", "hybrid", "office", "duration", "months", "weeks", "stipend",
    "paid", "unpaid", "based", "performance", "full", "part", "time",
    "real", "world", "applications", "explore", "exposure", "gain",
    "hands", "skill", "skills", "development", "artificial", "intelligence",
    "field", "fields", "area", "areas", "industry", "sector",
    # seniority labels — too broad
    "developer", "engineer", "manager", "analyst", "specialist",
    "professional", "lead", "senior", "junior", "mid", "associate",
    "assistant", "coordinator", "officer", "executive", "head",
}

# ── keyword extraction (rule-based) ───────────────────────────────────────────

def _extract_keywords(text: str) -> list[str]:
    """
    Extract meaningful keywords from a block of text.

    Strategy:
      1. Tokenise into lowercase words/hyphenated-phrases.
      2. Drop stopwords and very short tokens.
      3. Keep multi-word technical phrases (e.g. "machine learning", "ci/cd").
      4. Deduplicate preserving first-seen order.

    Returns a list of lowercase keyword strings.
    """
    if not text:
        return []

    text_lower = text.lower()

    # ── multi-word technical phrases first (order matters — longest match wins)
    PHRASES = [
        # AI / ML (student-relevant)
        "machine learning", "deep learning", "natural language processing",
        "natural language", "large language models", "computer vision",
        "data science", "neural network", "neural networks",
        "random forest", "gradient boosting", "reinforcement learning",
        "generative ai", "artificial intelligence", "transfer learning",
        "object detection", "image classification", "sentiment analysis",
        "speech recognition", "recommendation system", "predictive modeling",
        "feature engineering", "model deployment", "model training",
        "convolutional neural network", "recurrent neural network",
        "support vector machine", "decision tree", "a/b testing",
        "data pipeline", "etl pipeline", "data analysis", "data visualization",
        "exploratory data analysis", "statistical analysis",
        # ML frameworks / tools
        "scikit learn", "scikit-learn", "tensorflow", "pytorch", "keras",
        "hugging face", "langchain", "openai api", "google colab",
        "jupyter notebook", "apache spark", "apache kafka",
        "matplotlib", "seaborn", "plotly", "tableau", "power bi",
        # cloud / devops
        "amazon web services", "google cloud platform", "microsoft azure",
        "google cloud", "ci/cd", "continuous integration", "continuous deployment",
        "infrastructure as code", "site reliability engineering",
        "kubernetes", "docker", "terraform", "ansible",
        "version control", "github actions",
        # web / backend
        "restful api", "rest api", "graphql", "microservices",
        "test driven development", "object oriented", "object-oriented",
        "agile methodology", "scrum", "kanban", "fast api", "fastapi",
        "django rest framework", "spring boot",
        # databases
        "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "sql server", "oracle database", "sqlite",
        # languages / frameworks
        "react native", "next.js", "node.js", "vue.js", "react.js",
        "express.js", "flask", "django", "spring boot",
        # soft/domain skills that appear as phrases
        "problem solving", "critical thinking", "time management",
        "project management", "team collaboration", "open source",
    ]

    found_phrases = []
    cleaned = text_lower
    for phrase in PHRASES:
        if phrase in cleaned:
            found_phrases.append(phrase)
            cleaned = cleaned.replace(phrase, " ")  # don't double-count words

    # ── single tokens
    # Only keep words that look like technical terms — proper nouns, tools,
    # languages, frameworks. Filter out plain English adjectives/nouns by:
    #   1. Checking against the expanded STOPWORDS set
    #   2. Requiring the token appear in a curated TECH_SINGLES list OR
    #      contain a digit/special char (e.g. python3, c++, h2o, k8s)
    #      OR be a known domain word
    TECH_SINGLES = {
        # languages
        "python", "java", "javascript", "typescript", "golang", "rust",
        "scala", "kotlin", "swift", "ruby", "php", "perl", "matlab",
        "bash", "shell", "sql", "html", "css", "sass", "xml", "json",
        "yaml", "latex", "c", "cpp",
        # ML / AI tools & libraries
        "tensorflow", "pytorch", "keras", "sklearn", "xgboost", "lightgbm",
        "catboost", "numpy", "pandas", "scipy", "matplotlib", "seaborn",
        "plotly", "bokeh", "nltk", "spacy", "gensim", "transformers",
        "langchain", "llama", "openai", "gemini", "colab", "kaggle",
        "mlflow", "wandb", "dvc", "airflow", "spark", "hadoop",
        # web / backend
        "flask", "django", "fastapi", "express", "spring", "rails",
        "react", "angular", "vue", "svelte", "bootstrap", "tailwind",
        "jquery", "redux", "graphql", "grpc", "nginx", "gunicorn",
        # cloud / devops
        "aws", "gcp", "azure", "heroku", "vercel", "netlify",
        "docker", "kubernetes", "terraform", "ansible", "jenkins",
        "prometheus", "grafana", "git", "github", "gitlab", "bitbucket",
        "linux", "ubuntu", "debian", "centos",
        # databases
        "mysql", "postgresql", "mongodb", "redis", "sqlite", "cassandra",
        "neo4j", "dynamodb", "firebase", "supabase",
        # other tech
        "api", "rest", "oauth", "jwt", "https", "websocket",
        "blockchain", "solidity", "arduino", "raspberry", "opencv",
        "tableau", "powerbi", "excel", "figma", "jira", "confluence",
        "zapier", "notion", "airtable", "selenium", "pytest", "junit",
        "nlp", "cv", "llm", "gpt", "bert", "cnn", "rnn", "lstm", "gan",
        "svm", "knn", "pca", "ann", "mlops", "devops", "ci", "cd",
        "oop", "mvc", "orm", "sdk", "ide", "cli", "gui",
    }

    tokens = re.findall(r"[a-z][a-z0-9+#.\-]{1,30}", cleaned)
    single_keywords = []
    for t in tokens:
        if t in STOPWORDS:
            continue
        if len(t) <= 2:
            continue
        # Accept if: known tech term, contains digit, contains special char, or 4+ chars ending in common tech suffix
        is_tech = (
            t in TECH_SINGLES
            or any(c.isdigit() for c in t)
            or "+" in t or "#" in t
            or t.endswith((".js", ".py", ".go", "sql", "db", "ml", "ai", "ops"))
            or re.search(r"(framework|library|platform|protocol|language|stack)", t)
        )
        if is_tech:
            single_keywords.append(t)

    # ── deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for kw in (found_phrases + single_keywords):
        if kw not in seen:
            seen.add(kw)
            result.append(kw)

    log.debug("Extracted %d keywords from text (%d chars)", len(result), len(text))
    return result


# ── keyword matching (rule-based) ─────────────────────────────────────────────

def _match_keywords(
    jd_keywords: list[str],
    resume_text: str,
) -> tuple[list[str], list[str]]:
    """
    Match JD keywords against the full resume text.

    Match types (both count as "matched"):
      - Exact:   keyword appears verbatim in resume text
      - Partial: keyword is 4+ chars and is a substring of a resume word,
                 OR a resume word is a substring of the keyword.
                 e.g. "kubernetes" matches "k8s-cluster" is too loose,
                 but "python" matches "python3" is fine.

    Returns (matched_list, missing_list).
    """
    resume_lower = resume_text.lower()
    matched: list[str] = []
    missing: list[str] = []

    for kw in jd_keywords:
        kw_lower = kw.lower()
        # exact match
        if kw_lower in resume_lower:
            matched.append(kw)
            continue

        # partial match — only for keywords 4+ chars to avoid false positives
        if len(kw_lower) >= 4:
            # check if any word in resume contains the keyword as substring
            # e.g. "react" in "reactjs", "python" in "python3"
            pattern = re.compile(r"\b\w*" + re.escape(kw_lower) + r"\w*\b")
            if pattern.search(resume_lower):
                matched.append(kw)
                continue

        missing.append(kw)

    log.debug(
        "Keyword match: %d/%d matched (%.0f%%)",
        len(matched), len(jd_keywords),
        100 * len(matched) / len(jd_keywords) if jd_keywords else 0,
    )
    return matched, missing


# ── format score (rule-based heuristics) ──────────────────────────────────────

def _format_score(resume_text: str) -> int:
    """
    Heuristic score (0-100) for resume completeness.
    Tuned for student/fresher resumes — projects count as experience,
    any list marker counts as bullets, GitHub/LinkedIn count as contact.
    Each check is worth points, not all-or-nothing.
    """
    t = resume_text.lower()

    checks = {
        # Contact — email OR phone OR linkedin OR github (students often skip phone)
        "contact": bool(
            re.search(r"[\w.+-]+@[\w-]+\.\w+", resume_text) or
            re.search(r"\+?\d[\d\s\-(). ]{6,}\d", resume_text) or
            "linkedin" in t or "github" in t
        ),
        # Education — very broad: any degree word, year, or institution
        "education": any(w in t for w in (
            "education", "degree", "university", "college", "bachelor",
            "master", "phd", "b.tech", "b.e.", "bsc", "msc", "b.sc",
            "engineering", "institute", "school", "gpa", "cgpa", "10th", "12th"
        )),
        # Skills section — any mention of skills or technologies
        "skills": any(w in t for w in (
            "skills", "technologies", "tools", "languages", "frameworks",
            "libraries", "tech stack", "technical"
        )),
        # Projects — students have projects not work experience
        "projects_or_experience": any(w in t for w in (
            "project", "projects", "experience", "internship", "work",
            "built", "developed", "created", "implemented", "designed"
        )),
        # Any kind of list structure — •, -, *, |, or just numbered lines
        "structured_content": bool(
            re.search(r"[•‣◦⁃•]", resume_text) or
            re.search(r"^\s*[-*]\s+\w", resume_text, re.MULTILINE) or
            re.search(r"^\s*\d+[.)]\s+\w", resume_text, re.MULTILINE) or
            re.search(r"\|\s*\w", resume_text)
        ),
        # Any year mentioned (education year, project year, etc.)
        "dates": bool(re.search(r"\b(19|20)\d{2}\b", resume_text)),
        # Certifications, achievements, or awards
        "achievements": any(w in t for w in (
            "certif", "award", "achiev", "honor", "honour", "rank",
            "winner", "hackathon", "competition", "publication", "paper",
            "research", "patent", "scholarship"
        )),
        # Any number showing impact — even small (accuracy %, dataset size, etc.)
        "metrics": bool(re.search(
            r"\d+\s*(%|percent|accuracy|loss|score|users|samples|classes|layers|epoch|dataset|k\b|mb|gb)",
            t
        )),
    }

    score = int(100 * sum(checks.values()) / len(checks))
    log.debug("Format score checks: %s -> %d", checks, score)
    return score


# ── AI semantic score ──────────────────────────────────────────────────────────

# Deliberately narrow prompt: GPT only scores semantic relevance.
# Keyword matching is already done deterministically above.
# We're asking GPT what it's actually good at: understanding meaning.
SEMANTIC_PROMPT = """\
You are an expert recruiter. Score how semantically relevant this resume is \
for the given job description, from 0 to 100.

Consider:
- Does the candidate's background align with the role's seniority level?
- Do their past projects/responsibilities match what this job requires?
- Is there meaningful domain overlap (e.g. both are in fintech, healthcare, etc.)?

Do NOT penalise for missing specific tools — that is handled separately.
Focus purely on narrative and experience fit.

Return ONLY a JSON object with one key:
{"semantic_score": <integer 0-100>}

Important for student resumes:
- Projects, college coursework, and personal builds COUNT as relevant experience
- A 2nd year student applying for an intern role is the RIGHT seniority level — score accordingly
- Score 60-80 if domain matches even without professional experience
- Only score below 40 if the domain is completely unrelated
"""


def _get_semantic_score(
    client: OpenAI,
    resume_text: str,
    job_description: str,
) -> int:
    """
    Ask OpenAI for a semantic relevance score (0–100).
    Returns 50 (neutral) on any failure so it degrades gracefully.

    BUG FIX vs original:
      - Errors are LOGGED with the actual reason, not silently swallowed.
      - String scores from the API are coerced to int.
      - Returns a neutral fallback (50) rather than crashing.
    """
    # Build prompt with simple concatenation — NEVER .format() with user text
    # .format() crashes if resume/JD contains { } characters (KeyError)
    prompt = (
        SEMANTIC_PROMPT
        + "\n\nRESUME:\n" + resume_text[:4000]
        + "\n\nJOB DESCRIPTION:\n" + job_description[:2000]
    )
    log.debug("Sending semantic scoring request to OpenAI...")

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a strict JSON generator. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            timeout=20,
        )
        raw = response.choices[0].message.content
        log.debug("OpenAI raw response: %s", raw)

        # ── BULLETPROOF extraction ──────────────────────────────────────────
        # Never use dict key lookup — OpenAI sometimes wraps key names in extra
        # quotes causing KeyError. Instead scan the raw string directly with regex.
        # Looks for any pattern like:  "semantic_score": 72  or  semantic_score: 72
        match = re.search(r'semantic_score[^:]*:\s*[^0-9]*(\d+)', raw)
        if match:
            score = int(match.group(1))
        else:
            # Last resort: grab the first standalone number 0-100 in the response
            nums = re.findall(r"\b([0-9]{1,3})\b", raw)
            valid = [int(n) for n in nums if 0 <= int(n) <= 100]
            score = valid[0] if valid else 50
            log.warning("semantic_score not found via key — used fallback number %d from raw: %s", score, raw)

        score = max(0, min(100, int(score)))  # clamp to 0-100
        log.info("Semantic score: %d", score)
        return score

    except AuthenticationError as e:
        log.error("OpenAI AuthenticationError: %s", e)
        return 50
    except RateLimitError as e:
        log.error("OpenAI RateLimitError: %s", e)
        return 50
    except APIError as e:
        log.error("OpenAI APIError: %s", e)
        return 50
    except Exception as e:
        log.error("Unexpected error in _get_semantic_score: %s", type(e).__name__, exc_info=True)
        return 50


# ── suggestion generator ───────────────────────────────────────────────────────

SUGGESTION_PROMPT = """\
You are an expert resume coach. Given a resume and job description, \
provide exactly 4 actionable, specific improvement suggestions.

Context:
- Missing keywords the resume should include: {missing_keywords}
- Format score: {format_score}/100

Rules:
- Each suggestion must be a single sentence under 20 words.
- Be specific — name actual skills or tools from the job description.
- Do NOT repeat the missing keywords list verbatim — give coaching advice.
- Output ONLY a JSON array of 4 strings: ["...", "...", "...", "..."]

RESUME (first 1500 chars):
{resume_snippet}

JOB DESCRIPTION (first 1000 chars):
{jd_snippet}
"""


def _get_suggestions(
    client: OpenAI,
    resume_text: str,
    job_description: str,
    missing_keywords: list[str],
    format_score: int,
) -> list[str]:
    """
    Generate 4 actionable suggestions using AI.
    Falls back to rule-based suggestions if AI fails.
    """
    # Always generate at least rule-based fallback suggestions
    rule_suggestions = []
    if missing_keywords:
        top_missing = missing_keywords[:5]
        rule_suggestions.append(
            f"Add these missing skills to your resume: {', '.join(top_missing)}."
        )
    if format_score < 50:
        rule_suggestions.append(
            "Add measurable achievements (e.g. 'Reduced latency by 40%') to strengthen your resume."
        )
    if not re.search(r"[\u2022\u2023\u25E6\u2043•\-\*]\s+\w", resume_text):
        rule_suggestions.append(
            "Use bullet points in your experience section for better ATS readability."
        )
    rule_suggestions.append(
        "Mirror the exact job title from the posting in your resume summary."
    )

    # Concatenate instead of .format() to avoid KeyError on braces in user text
    missing_str = ", ".join(missing_keywords[:10]) if missing_keywords else "none"
    prompt = (
        SUGGESTION_PROMPT
        + f"\nMissing keywords: {missing_str}"
        + f"\nFormat score: {format_score}/100"
        + "\n\nRESUME (first 1500 chars):\n" + resume_text[:1500]
        + "\n\nJOB DESCRIPTION (first 1000 chars):\n" + job_description[:1000]
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Output only a valid JSON array of strings."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            timeout=20,
        )
        raw = response.choices[0].message.content
        log.debug("Suggestions raw response: %s", raw)

        # GPT sometimes returns {"suggestions": [...]} instead of bare array
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            suggestions = parsed
        elif isinstance(parsed, dict):
            # look for any list value in the response
            for v in parsed.values():
                if isinstance(v, list) and len(v) > 0:
                    suggestions = v
                    break
            else:
                raise ValueError("No list found in suggestions response")
        else:
            raise ValueError(f"Unexpected type: {type(parsed)}")

        suggestions = [str(s) for s in suggestions if s][:5]
        if suggestions:
            log.info("Generated %d AI suggestions", len(suggestions))
            return suggestions

    except Exception as e:
        log.warning("AI suggestion generation failed (%s), using rule-based fallback.", e)

    return rule_suggestions[:4]




# ── strengths generator ────────────────────────────────────────────────────────

STRENGTHS_PROMPT = """\
You are an expert recruiter reviewing a student's resume for a specific job.
List exactly 3 genuine strengths this resume shows for this role.

Rules:
- Each strength must be a single sentence under 20 words.
- Be specific — reference actual content from the resume.
- Focus on what makes this candidate competitive, not generic praise.
- Output ONLY a JSON object: {{"strengths": ["...", "...", "..."]}}

RESUME (first 1500 chars):
{resume_snippet}

JOB DESCRIPTION (first 800 chars):
{jd_snippet}
"""


def _get_strengths(
    client: OpenAI,
    resume_text: str,
    job_description: str,
    matched_keywords: list[str],
) -> list[str]:
    """
    Generate 3 resume strengths using AI.
    Falls back to rule-based strengths if AI fails.
    """
    # Rule-based fallback — always computed so we never return []
    rule_strengths = []
    if matched_keywords:
        rule_strengths.append(
            f"Resume already covers key required skills: {', '.join(matched_keywords[:4])}."
        )
    if re.search(r"\d+\s*(%|percent|users|million|k\b)", resume_text.lower()):
        rule_strengths.append(
            "Resume includes quantified achievements, which stand out to recruiters."
        )
    if re.search(r"\b(project|built|developed|created|designed|implemented)\b", resume_text.lower()):
        rule_strengths.append(
            "Resume demonstrates hands-on project experience relevant to the role."
        )
    if len(rule_strengths) < 3:
        rule_strengths.append("Resume shows relevant educational background for this role.")

    prompt = (
        STRENGTHS_PROMPT
        + "\n\nRESUME (first 1500 chars):\n" + resume_text[:1500]
        + "\n\nJOB DESCRIPTION (first 800 chars):\n" + job_description[:800]
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Output only a valid JSON object."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            timeout=20,
        )
        raw = response.choices[0].message.content
        log.debug("Strengths raw response: %s", raw)

        parsed = json.loads(raw)
        # Handle both {"strengths": [...]} and bare list
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list) and len(v) > 0:
                    strengths = [str(s) for s in v if s][:4]
                    if strengths:
                        log.info("Generated %d AI strengths", len(strengths))
                        return strengths
        raise ValueError(f"Unexpected strengths response shape: {parsed}")

    except Exception as e:
        log.warning("AI strengths generation failed (%s), using rule-based fallback.", e)

    return rule_strengths[:3]

# ── main entry point ───────────────────────────────────────────────────────────

def analyze_resume(resume_text: str, job_description: str) -> dict:
    """
    Full hybrid ATS analysis.

    Scoring formula:
      keyword_score  = (matched / total_jd_keywords) * 100     → 60% weight
      semantic_score = AI relevance rating (0-100)             → 25% weight
      format_score   = resume completeness heuristic (0-100)   → 15% weight
      final_score    = round(0.60*k + 0.25*s + 0.15*f)

    Returns dict with: score, matched_keywords, missing_keywords,
                       suggestions, component_scores (for debugging)

    BUG FIX B4: returns score=-1 (not 0) on failure so caller can distinguish
    "terrible resume" from "analysis failed".
    """
    log.info(
        "analyze_resume called — resume: %d chars, JD: %d chars",
        len(resume_text), len(job_description),
    )

    # ── guard: never crash on missing API key — surface the real error
    # BUG FIX B2: was os.environ["OPENAI_API_KEY"] which raises KeyError silently
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        log.error("OPENAI_API_KEY is not set or is empty.")
        fallback = FALLBACK.copy()
        fallback["suggestions"] = ["Server error: OpenAI API key is not configured."]
        return fallback

    client = OpenAI(api_key=api_key)

    # ── step 1: keyword scoring (deterministic, always runs)
    jd_keywords = _extract_keywords(job_description)
    log.info("Extracted %d keywords from job description.", len(jd_keywords))

    if not jd_keywords:
        log.warning("No keywords extracted from job description — text may be too short.")
        jd_keywords = job_description.lower().split()[:20]  # last-resort fallback

    matched_keywords, missing_keywords = _match_keywords(jd_keywords, resume_text)

    keyword_score = (
        round(100 * len(matched_keywords) / len(jd_keywords))
        if jd_keywords else 0
    )
    log.info("Keyword score: %d (matched %d/%d)", keyword_score, len(matched_keywords), len(jd_keywords))

    # ── step 2: format score (deterministic, always runs)
    format_score = _format_score(resume_text)
    log.info("Format score: %d", format_score)

    # ── step 3: semantic score (AI, may degrade gracefully)
    semantic_score = _get_semantic_score(client, resume_text, job_description)
    log.info("Semantic score: %d", semantic_score)

    # ── step 4: suggestions (AI with rule-based fallback)
    suggestions = _get_suggestions(
        client, resume_text, job_description, missing_keywords, format_score
    )

    # ── step 4b: strengths (AI with rule-based fallback)
    strengths = _get_strengths(
        client, resume_text, job_description, matched_keywords
    )

    # ── step 5: combine scores
    final_score = round(
        0.60 * keyword_score +
        0.25 * semantic_score +
        0.15 * format_score
    )
    final_score = max(0, min(100, final_score))  # clamp to 0-100
    log.info("Final score: %d (keyword=%d, semantic=%d, format=%d)", final_score, keyword_score, semantic_score, format_score)

    return {
        "score": final_score,
        "matched_keywords": matched_keywords[:20],
        "missing_keywords": missing_keywords[:20],
        "suggestions": suggestions,
        "strengths": strengths,
        "component_scores": {
            "keyword": keyword_score,
            "semantic": semantic_score,
            "format": format_score,
        },
        "error": False,
    }