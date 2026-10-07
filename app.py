"""
app.py — ResumeAI Student Frontend
=====================================
Changes from previous version:
  - API key input REMOVED — backend handles it via environment variable only
  - Calls /analyze-resume endpoint (new primary endpoint)
  - Added Strengths section to results
  - Full product-quality UI: score gauge, coloured badges, card sections
  - Sidebar simplified to About + health check only
  - All error handling and debug expander preserved
"""

import streamlit as st
import requests
from utils.pdf_parser import extract_text_from_pdf

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="ResumeAI — Student Resume Analyzer",
    page_icon="🎯",
    layout="wide",
)

# ── custom CSS — minimal, just tightens up Streamlit's default gaps ───────────
st.markdown("""
<style>
/* Section cards */
.result-card {
    background: #f8f9fa;
    border-radius: 12px;
    padding: 1.2rem 1.5rem;
    margin-bottom: 1rem;
    border-left: 4px solid #667eea;
}
/* Keyword badges */
.badge-green {
    display: inline-block;
    background: #d4edda;
    color: #155724;
    border-radius: 20px;
    padding: 2px 12px;
    margin: 3px;
    font-size: 0.85rem;
    font-weight: 500;
}
.badge-red {
    display: inline-block;
    background: #f8d7da;
    color: #721c24;
    border-radius: 20px;
    padding: 2px 12px;
    margin: 3px;
    font-size: 0.85rem;
    font-weight: 500;
}
/* Score number */
.score-big {
    font-size: 4rem;
    font-weight: 700;
    line-height: 1;
}
.score-label {
    font-size: 1rem;
    margin-top: 4px;
}
</style>
""", unsafe_allow_html=True)


# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎯 ResumeAI")
    st.markdown(
        "Upload your resume and paste any job description. "
        "We'll tell you exactly how well you match and what to fix."
    )
    st.markdown("---")
    st.markdown("**How scoring works**")
    st.markdown("""
- **60%** Keyword match
- **25%** Semantic fit (AI)
- **15%** Resume format
""")
    st.markdown("---")

    # Health check — useful for developers, harmless for students
    if st.button("🔍 Check backend status"):
        try:
            r = requests.get("http://localhost:8000/health", timeout=3)
            data = r.json()
            if data.get("openai_key_configured"):
                st.success("✅ Backend online")
            else:
                st.warning("⚠️ Backend running but API key not set")
        except requests.exceptions.ConnectionError:
            st.error("❌ Backend offline (port 8000)")

    st.markdown("---")
    st.caption("No data is stored. Your resume stays private.")


# ── hero ──────────────────────────────────────────────────────────────────────
st.markdown("# 🎯 ResumeAI — Student Resume Analyzer")
st.markdown(
    "##### Know your match score before you apply. Get specific fixes, not vague advice."
)
st.markdown("---")


# ── input section ─────────────────────────────────────────────────────────────
col_left, col_right = st.columns([1, 1], gap="large")

with col_left:
    st.markdown("### 📄 Upload Your Resume")
    uploaded_file = st.file_uploader(
        "PDF format only, max 5 MB",
        type=["pdf"],
        label_visibility="collapsed",
    )
    if uploaded_file:
        st.success(f"✅ Loaded: **{uploaded_file.name}**")

with col_right:
    st.markdown("### 💼 Paste Job Description")
    job_description = st.text_area(
        "Job description",
        height=220,
        placeholder="Paste the full job posting here — the more detail the better...",
        label_visibility="collapsed",
    )
    word_count = len(job_description.split()) if job_description.strip() else 0
    if word_count > 0:
        colour = "green" if word_count >= 50 else "orange"
        st.caption(f":{colour}[{word_count} words]")

st.markdown("")
analyze_btn = st.button("🚀 Analyze My Resume", type="primary", use_container_width=True)


# ── validation ────────────────────────────────────────────────────────────────
def validate_inputs(resume_text: str, jd_text: str) -> bool:
    if resume_text.startswith("__PDF_ERROR__:"):
        reason = resume_text.replace("__PDF_ERROR__:", "")
        st.error(f"PDF error: {reason}")
        return False
    if not resume_text.strip():
        st.error(
            "Could not extract text from this PDF. "
            "It may be a scanned image — try a text-based PDF instead."
        )
        return False
    if not jd_text.strip():
        st.error("Please paste a job description before analyzing.")
        return False
    if len(jd_text.strip().split()) < 20:
        st.warning(
            "The job description looks very short. "
            "Paste the full posting for more accurate results."
        )
    return True


# ── analysis and results ──────────────────────────────────────────────────────
if analyze_btn:
    if uploaded_file is None:
        st.error("Please upload a PDF resume first.")
    else:
        resume_bytes = uploaded_file.read()
        if len(resume_bytes) > 5 * 1024 * 1024:
            st.error("File is over 5 MB. Please compress or trim your resume.")
        else:
            extracted_text = extract_text_from_pdf(resume_bytes)

            if validate_inputs(extracted_text, job_description):
                with st.spinner("Analyzing your resume... this takes 10–20 seconds"):

                    payload = {
                        "resume_text": extracted_text,
                        "job_description": job_description.strip(),
                    }
                    raw_response = None

                    try:
                        # Use the primary API endpoint exposed by api.py.
                        response = requests.post(
                            "http://localhost:8000/analyze",
                            json=payload,
                            timeout=60,
                        )
                        raw_response = response

                        # ── SUCCESS ──────────────────────────────────────────
                        if response.status_code == 200:
                            result = response.json()
                            score = result.get("score", 0)
                            matched  = result.get("matched_keywords", [])
                            missing  = result.get("missing_keywords", [])
                            suggestions = result.get("suggestions", [])
                            strengths   = result.get("strengths", [])
                            components  = result.get("component_scores", {})

                            st.markdown("---")
                            st.markdown("## 📊 Your Results")

                            # ── SCORE SECTION ─────────────────────────────────
                            score_col, verdict_col = st.columns([1, 2], gap="large")

                            with score_col:
                                if score >= 70:
                                    score_colour = "#28a745"
                                    verdict = "Strong Match 🟢"
                                    verdict_msg = "You're competitive for this role. Tighten the missing skills and apply with confidence."
                                elif score >= 45:
                                    score_colour = "#fd7e14"
                                    verdict = "Moderate Match 🟡"
                                    verdict_msg = "You have a foundation but the gaps are noticeable. Fix the missing skills before applying."
                                else:
                                    score_colour = "#dc3545"
                                    verdict = "Weak Match 🔴"
                                    verdict_msg = "Significant gaps between your resume and this role. Use the suggestions below to improve."

                                st.markdown(
                                    f"<div style='text-align:center'>"
                                    f"<div class='score-big' style='color:{score_colour}'>{score}</div>"
                                    f"<div class='score-label' style='color:{score_colour}'><b>/ 100</b></div>"
                                    f"<div style='margin-top:8px;font-size:1.1rem'><b>{verdict}</b></div>"
                                    f"</div>",
                                    unsafe_allow_html=True,
                                )
                                st.progress(score / 100.0)

                            with verdict_col:
                                st.markdown(f"**{verdict_msg}**")
                                st.markdown("")

                                if components:
                                    st.markdown("**Score breakdown:**")
                                    c1, c2, c3 = st.columns(3)
                                    c1.metric(
                                        "Keywords",
                                        f"{components.get('keyword', 0)}",
                                        help="60% of final score — how many JD keywords appear in your resume",
                                    )
                                    c2.metric(
                                        "Semantic fit",
                                        f"{components.get('semantic', 0)}",
                                        help="25% of final score — AI judgment of overall experience fit",
                                    )
                                    c3.metric(
                                        "Format",
                                        f"{components.get('format', 0)}",
                                        help="15% of final score — resume completeness (contact info, bullets, dates, metrics)",
                                    )

                            st.markdown("---")

                            # ── KEYWORDS SECTION ─────────────────────────────
                            kw_col1, kw_col2 = st.columns(2, gap="large")

                            with kw_col1:
                                st.markdown("### ✅ Matched Keywords")
                                st.caption(f"{len(matched)} keywords from the JD found in your resume")
                                if matched:
                                    badges = "".join(
                                        f'<span class="badge-green">{kw}</span>'
                                        for kw in matched
                                    )
                                    st.markdown(badges, unsafe_allow_html=True)
                                else:
                                    st.info("No matching keywords found. Your resume may use different terminology.")

                            with kw_col2:
                                st.markdown("### ❌ Missing Keywords")
                                st.caption(f"{len(missing)} important JD keywords not found in your resume")
                                if missing:
                                    badges = "".join(
                                        f'<span class="badge-red">{kw}</span>'
                                        for kw in missing
                                    )
                                    st.markdown(badges, unsafe_allow_html=True)
                                else:
                                    st.success("No critical keywords missing — great coverage!")

                            st.markdown("---")

                            # ── STRENGTHS + SUGGESTIONS ───────────────────────
                            str_col, sug_col = st.columns(2, gap="large")

                            with str_col:
                                st.markdown("### 💪 Your Strengths")
                                st.caption("What's working well in your resume for this role")
                                if strengths:
                                    for item in strengths:
                                        st.markdown(f"✔️ {item}")
                                else:
                                    st.info("Strengths analysis unavailable.")

                            with sug_col:
                                st.markdown("### 💡 How to Improve")
                                st.caption("Specific actions to raise your score")
                                if suggestions:
                                    for item in suggestions:
                                        st.markdown(f"→ {item}")
                                else:
                                    st.info("No specific suggestions — your resume looks solid!")

                            st.markdown("---")
                            st.caption(
                                "Scores are AI estimates, not guarantees. "
                                "Use them as a guide, not a final verdict."
                            )

                        # ── ERROR RESPONSES ───────────────────────────────────
                        elif response.status_code == 400:
                            detail = response.json().get("detail", "Invalid input.")
                            st.error(f"Input error: {detail}")

                        elif response.status_code == 503:
                            detail = response.json().get("detail", "Service unavailable.")
                            st.error(f"Service error: {detail}")
                            st.info(
                                "The AI backend isn't available right now. "
                                "If you're running this locally, make sure the server "
                                "is started with the OPENAI_API_KEY environment variable set."
                            )

                        else:
                            detail = response.json().get("detail", "Unknown error.")
                            st.error(f"Error {response.status_code}: {detail}")

                    except requests.exceptions.ConnectionError:
                        st.error(
                            "Cannot connect to the backend on port 8000. "
                            "Start it with: `uvicorn api:app --reload`"
                        )
                    except requests.exceptions.Timeout:
                        st.error(
                            "Analysis timed out after 60 seconds. "
                            "Try a shorter resume or job description."
                        )
                    except Exception as e:
                        st.error(f"Unexpected error: {type(e).__name__}: {e}")

                    # ── DEBUG EXPANDER (harmless in production, useful in dev)
                    if raw_response is not None:
                        with st.expander("🔧 Developer debug info"):
                            st.code(
                                f"Status: {raw_response.status_code}\n\n"
                                + raw_response.text[:3000],
                                language="json",
                            )