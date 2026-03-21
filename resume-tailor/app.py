import streamlit as st
import os
import json
import re
from tailor_resume import JobScraper, ResumeTailor, GeminiTailor, LaTeXEngine
from loguru import logger
import sys
from dotenv import load_dotenv

load_dotenv()

# Streamlit UI Configuration
st.set_page_config(page_title="Resume Tailor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f5f1e9; color: #2c3e50; font-family: 'Inter', sans-serif; }
    .stButton>button { background-color: #2c3e50; color: white; border-radius: 8px; font-weight: 600; width: 100%; }
    .resume-preview { background-color: white; padding: 40px; border-radius: 2px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); font-family: serif; line-height: 1.4; color: #1a1a1a; min-height: 800px; }
    .health-score { font-size: 24px; font-weight: bold; color: #27ae60; }
    .stExpander { border: none !important; box-shadow: none !important; }
    .stDownloadButton button { background-color: #27ae60 !important; color: white !important; }
    /* Force tabs to spread evenly across full width */
    button[data-baseweb="tab"] { flex: 1; text-align: center; }
    </style>
    """, unsafe_allow_html=True)

st.title("Resume Tailor")
st.caption("Enter a target job URL or paste the job description and tailor your resume to match.")

# Sidebar - Settings & Keys
with st.sidebar:
    st.header("Control Panel")
    api_key = st.text_input("Gemini API Key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
    
    st.divider()
    st.header("Experience Source")
    uploaded_file = st.file_uploader("Upload your experience.json", type="json")
    if uploaded_file:
        source_data = json.load(uploaded_file)
        st.success("Custom source loaded!")
    else:
        with open("experience.json", "r") as f:
            source_data = json.load(f)
        st.info("Using default experience.json")
    
    st.divider()
    force_run = st.checkbox("Force Re-Tailor", value=False, help="When checked, the system will ignore any previously saved results for this company/role and make a fresh API call to Gemini. Use this if you've updated your experience.json, want different keyword targeting, or the previous run had issues. Costs 1 API credit.")

# Main Interface
col_input, col_output = st.columns([1, 1.2])

with col_input:
    st.markdown("### Target")
    job_target = st.text_input("Job URL", placeholder="Enter URL")
    job_text = st.text_area("Or Paste Job Description", height=200, placeholder="Enter job description")

    if st.button("Tailor Resume"):
        if not api_key:
            st.error("API Key required.")
        elif not (job_target or job_text):
            st.error("Target info required.")
        else:
            if job_target and job_text:
                st.info("Tailoring with the Job Description.")
            elif job_text:
                st.info("Tailoring with the Job Description.")
            else:
                st.info("Tailoring with the Job URL.")
            status_container = st.empty()
            with st.spinner("Running AI Pipeline..."):
                try:
                    # 1. Initialize Gemini first for use in scraping
                    gemini = GeminiTailor(api_key)
                    
                    # 2. Scrape
                    if job_target and job_text:
                        company, title, _ = JobScraper.get_job_info(job_target, gemini_model=gemini.client)
                        jd_content = job_text
                    elif job_target:
                        company, title, jd_content = JobScraper.get_job_info(job_target, gemini_model=gemini.client)
                    else:
                        company, title, jd_content = JobScraper.get_job_info(job_text, gemini_model=gemini.client)
                    if not jd_content:
                        status_container.error("Scraping Failed.")
                        if "res_json" in st.session_state: del st.session_state['res_json']
                        st.error("**Failed to extract job description.**")
                        st.warning("The provided URL format might be unsupported or blocked by the platform. Please copy the job description text and use the **'Paste Job Description'** box instead.")
                        st.stop()
                    
                    status_container.info(f"Analyzing {title} @ {company}...")
                    
                    # 3. Cache Check Logic
                    path = os.path.join("tailored_resumes", company.lower().replace(" ", "_"), title.lower().replace(" ", "_"))
                    is_cached = os.path.exists(path) and not force_run
                    
                    import hashlib
                    current_source_hash = hashlib.md5(json.dumps(source_data, sort_keys=True).encode()).hexdigest()

                    
                    if is_cached:
                        with open(os.path.join(path, "metadata.json"), "r") as f:
                            res_json = json.load(f)
                        
                        # Cache Integrity: If cache contains 'FALLBACK', force a re-run
                        # Check experience and projects for fallback rationales
                        has_fallback = False
                        for exp in res_json.get('experience', []):
                            for b in exp.get('bullets', []):
                                if "FALLBACK" in b.get('rationale', ''): has_fallback = True
                        
                        meta = res_json.get('metadata', {})
                        cached_source_hash = meta.get('source_hash') if isinstance(meta, dict) else None
                        
                        if has_fallback:
                            logger.info(f"Invalidating cache for {company} - found fallback bullets.")
                            is_cached = False
                        elif cached_source_hash != current_source_hash:
                            logger.info(f"Invalidating cache for {company} - source resume/experience has changed.")
                            is_cached = False
                        else:
                            status_container.success(f"Retrieved cached result for {company}!")
                            logger.success(f"CACHE HIT: Successfully loaded tailored resume for {title} @ {company} from local cache.")
                            st.success(f"Successfully loaded '{company}' resume from cache, skipping API calls.")
                            with open(os.path.join(path, "resume.tex"), "r") as f:
                                res_tex = f.read()

                    if not is_cached:
                        # 4. Process
                        tailor = ResumeTailor("experience.json", "resume_template.tex")
                        tailor.exp_json = source_data # Inject source
                        latex = LaTeXEngine(tailor.template)
                        
                        status_container.info("Executing Hallucination-Safe Rephrasing...")
                        res_obj = gemini.tailor_experience(jd_content, source_data)
                        
                        if res_obj.metadata:
                            res_obj.metadata.source_hash = current_source_hash
                        
                        status_container.info("Generating LaTeX & Escaping Symbols...")
                        res_tex = latex.populate(res_obj, source_data)
                        
                        tailor.save_outputs(path, res_obj, res_tex)
                        res_json = res_obj.model_dump()

                    st.session_state['res_tex'] = res_tex
                    st.session_state['res_json'] = res_json
                    st.session_state['company'] = company
                    st.session_state['jd_content'] = jd_content
                    status_container.success("Done!")
                    
                except Exception as e:
                    if "res_json" in st.session_state: del st.session_state['res_json']
                    
                    err_msg = str(e)
                    if err_msg.startswith("ALL_QUOTA_EXHAUSTED") or "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                        st.error("**Gemini Quota Exhausted** — Daily free-tier limits reached. Resets at midnight Pacific Time.")
                        st.info("**Options:** Wait for midnight PT reset · Use a paid API key · Paste the JD text directly instead of a URL.")
                    elif "ClientError" in err_msg:
                        st.error(f"**AI Connection Error**: {err_msg}")
                    else:
                        st.error(f"**Pipeline Failure**: {err_msg}")
                    
                    status_container.error("Process Aborted.")

if "res_json" in st.session_state:
    with col_output:
        # 📈 Stats Header
        meta = st.session_state['res_json'].get('metadata') or {}
        all_bullets = []
        for e in st.session_state['res_json']['experience']: all_bullets.extend(e['bullets'])
        for p in st.session_state['res_json']['projects']: all_bullets.extend(p['bullets'])
        total_bullets = len(all_bullets)
        rejected_count = sum(1 for b in all_bullets if "REJECTED" in b.get('rationale', ''))
        passed_count = total_bullets - rejected_count
        guard_pct = round((passed_count / total_bullets) * 100) if total_bullets else 100
        
        s1, s2, s3 = st.columns([1, 1, 1.5])
        with s1:
            st.metric("ATS Match", f"{meta.get('total_score', 0)}%")
        with s2:
            st.metric("Keywords", f"{len(meta.get('found_keywords', []))}/{len(meta.get('target_keywords', []))}")
        with s3:
            st.metric("Safety Guard", f"{guard_pct}% Passed", help=f"{passed_count}/{total_bullets} bullets passed hallucination checks. {rejected_count} reverted to originals. See the Hallucination Rejects tab for details.")
        
        st.caption(f"**Target Keywords:** {', '.join(meta.get('target_keywords', []))}")
        
        c_found, c_missing = st.columns(2)
        with c_found:
            if meta.get('found_keywords'):
                st.success("**Matched Keywords:**\n" + "\n".join([f"- {k}" for k in meta.get('found_keywords', [])]))
        with c_missing:
            if meta.get('missing_keywords'):
                st.warning("**Missing Keywords:**\n" + "\n".join([f"- {k}" for k in meta.get('missing_keywords', [])]))

        jd_display = st.session_state.get('jd_content', '')
        if jd_display:
            with st.expander("View Extracted Job Description (Keywords Highlighted)"):
                # Sort keywords by length descending to prevent partial replacements (e.g. "Software" inside "Software Engineering")
                sorted_keywords = sorted(meta.get('target_keywords', []), key=len, reverse=True)
                for k in sorted_keywords:
                    # Case-insensitive yellow highlight
                    jd_display = re.sub(f"(?i)({re.escape(k)})", r'<mark style="background-color:#ffe58f;padding:0 2px;border-radius:2px;color:#000;font-weight:bold;">\1</mark>', jd_display)
                st.markdown(f'<div style="white-space: pre-wrap; font-size:14px; line-height:1.6; color:#ddd;">{jd_display}</div>', unsafe_allow_html=True)

        tab_preview, tab_diff, tab_guard, tab_tex = st.tabs(["Resume Preview", "AI Tailoring Diff", "Hallucination Rejects", "LaTeX Code"])
        
        with tab_preview:
            # Build the entire resume as a single HTML string for proper rendering
            res_data = st.session_state['res_json']
            contact = source_data.get('contact', {})
            skills = source_data.get('skills', {})
            education = source_data.get('education', {})
            
            html = f"""
            <div style="
                background: #fff; color: #222; padding: 40px 50px; 
                max-width: 800px; margin: 0 auto; 
                font-family: 'Times New Roman', Georgia, serif; font-size: 11pt; line-height: 1.4;
                border: 1px solid #ddd; box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            ">
                <div style="text-align:center; margin-bottom: 8px;">
                    <div style="font-size: 22pt; font-weight: bold; letter-spacing: 1px;">{contact.get('name', '')}</div>
                    <div style="font-size: 9pt; color: #555; margin-top: 4px;">
                        {contact.get('email', '')} &nbsp;|&nbsp; {contact.get('phone', '')} &nbsp;|&nbsp; {contact.get('linkedin', '')}
                    </div>
                </div>
                <hr style="border: none; border-top: 1.5px solid #222; margin: 8px 0 12px 0;">
            """
            
            # Education
            if education:
                html += '<div style="font-size: 11pt; font-weight: bold; border-bottom: 1px solid #999; margin-bottom: 6px;">EDUCATION</div>'
                if isinstance(education, dict):
                    school = education.get('school', '')
                    degree = education.get('degree', '')
                    grad = education.get('graduation', '')
                    html += f'<div style="display:flex; justify-content:space-between;"><b>{school}</b><span>{grad}</span></div>'
                    html += f'<div style="margin-bottom: 8px;">{degree}</div>'
                elif isinstance(education, list):
                    for edu in education:
                        school = edu.get('school', '')
                        degree = edu.get('degree', '')
                        grad = edu.get('graduation', '')
                        html += f'<div style="display:flex; justify-content:space-between;"><b>{school}</b><span>{grad}</span></div>'
                        html += f'<div style="margin-bottom: 8px;">{degree}</div>'

            # Experience
            html += '<div style="font-size: 11pt; font-weight: bold; border-bottom: 1px solid #999; margin: 12px 0 6px 0;">EXPERIENCE</div>'
            for exp in res_data['experience']:
                html += f"""
                <div style="display:flex; justify-content:space-between; margin-top: 6px;">
                    <div><b>{exp['company']}</b> &mdash; <i>{exp['role']}</i></div>
                    <div style="font-size: 9pt; color: #555;">{exp.get('dates', '')}</div>
                </div>
                <div style="font-size: 8pt; color: #777; margin-bottom: 3px;">{exp.get('location', '')}</div>
                <ul style="margin: 2px 0 8px 18px; padding: 0;">
                """
                for b in exp['bullets']:
                    html += f'<li style="margin-bottom: 2px;">{b["tailored"]}</li>'
                html += '</ul>'

            # Projects
            html += '<div style="font-size: 11pt; font-weight: bold; border-bottom: 1px solid #999; margin: 12px 0 6px 0;">PROJECTS</div>'
            for prj in res_data['projects']:
                html += f"""
                <div style="margin-top: 6px;"><b>{prj['name']}</b> &mdash; <i>{prj['role']}</i></div>
                <ul style="margin: 2px 0 8px 18px; padding: 0;">
                """
                for b in prj['bullets']:
                    html += f'<li style="margin-bottom: 2px;">{b["tailored"]}</li>'
                html += '</ul>'

            # Skills
            if skills:
                html += '<div style="font-size: 11pt; font-weight: bold; border-bottom: 1px solid #999; margin: 12px 0 6px 0;">TECHNICAL SKILLS</div>'
                for cat, items in skills.items():
                    items_str = ', '.join(items) if isinstance(items, list) else str(items)
                    html += f'<div style="margin-bottom: 3px;"><b>{cat}:</b> {items_str}</div>'

            html += '</div>'
            
            st.markdown(html, unsafe_allow_html=True)
            
            st.divider()
            st.download_button("Download LaTeX (.tex)", st.session_state['res_tex'], file_name=f"{st.session_state['company']}_resume.tex")

        with tab_diff:
            st.info("Showing bullets successfully tailored by the AI to match the Job Description.")
            all_b = []
            for e in st.session_state['res_json']['experience']: all_b.extend(e['bullets'])
            for p in st.session_state['res_json']['projects']: all_b.extend(p['bullets'])
            
            changed_bullets = [b for b in all_b if b['original'] != b['tailored']]
            if not changed_bullets:
                st.write("No bullets were modified in this run.")
            
            import difflib
            for i, b in enumerate(changed_bullets):
                # Word-level diff
                orig_words = b['original'].split()
                tail_words = b['tailored'].split()
                sm = difflib.SequenceMatcher(None, orig_words, tail_words)
                
                diff_html = ""
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    if op == 'equal':
                        diff_html += ' '.join(orig_words[i1:i2]) + ' '
                    elif op == 'delete':
                        removed = ' '.join(orig_words[i1:i2])
                        diff_html += f'<span style="background:#fcc;color:#900;text-decoration:line-through;padding:1px 3px;border-radius:3px;">{removed}</span> '
                    elif op == 'insert':
                        added = ' '.join(tail_words[j1:j2])
                        diff_html += f'<span style="background:#cfc;color:#060;font-weight:bold;padding:1px 3px;border-radius:3px;">{added}</span> '
                    elif op == 'replace':
                        removed = ' '.join(orig_words[i1:i2])
                        added = ' '.join(tail_words[j1:j2])
                        diff_html += f'<span style="background:#fcc;color:#900;text-decoration:line-through;padding:1px 3px;border-radius:3px;">{removed}</span> '
                        diff_html += f'<span style="background:#cfc;color:#060;font-weight:bold;padding:1px 3px;border-radius:3px;">{added}</span> '
                
                st.markdown(
                    f'<div style="font-size:10pt;line-height:1.8;padding:12px 14px;border:1px solid #444;border-radius:6px;background:#1e1e1e;color:#ccc;margin-bottom:2px;">{diff_html.strip()}</div>'
                    f'<div style="font-size:8pt;color:#888;margin:0 0 20px 4px;">{b["rationale"]}</div>',
                    unsafe_allow_html=True
                )

        with tab_guard:
            st.error("Showing bullets that the AI attempted to change, but were REJECTED by the Hallucination Guard for adding unverified Proper Nouns or Metrics.")
            
            rejected_bullets = [b for b in all_b if "⚠️ REJECTED" in b['rationale']]
            if not rejected_bullets:
                st.success("Clean run! The guard caught zero hallucinations.")
                
            for b in rejected_bullets:
                with st.expander(f"Blocked: {b['original'][:60]}..."):
                    st.markdown("**Safe Original (Kept):**")
                    st.write(b['original'])
                    st.markdown("**Caught AI Rationale:**")
                    st.warning(b['rationale'])

        with tab_tex:
            st.code(st.session_state['res_tex'], language="latex")
else:
    with col_output:
        st.info("Input a job target to see your tailored resume here.")
