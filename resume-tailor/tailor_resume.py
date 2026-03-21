import sys
import os
import json
from loguru import logger
from dotenv import load_dotenv

# Re-export exactly what app.py needs
from resume_builder import JobScraper, ResumeTailor, GeminiTailor, LaTeXEngine

def main():
    load_dotenv()
    logger.remove()
    logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>", colorize=True)

    if len(sys.argv) < 2: sys.exit(1)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: logger.error("MISSING API KEY"); sys.exit(1)

    tailor = ResumeTailor("experience.json", "resume_template.tex")
    gemini = GeminiTailor(api_key)
    latex = LaTeXEngine(tailor.template)

    url_or_text = sys.argv[1]
    company, title, jd = JobScraper.get_job_info(url_or_text, gemini_model=gemini.client)
    if not jd: sys.exit(1)

    import hashlib
    current_hash = hashlib.md5(json.dumps(tailor.exp_json, sort_keys=True).encode()).hexdigest()

    company_slug = company.lower().replace(" ", "_")
    title_slug = title.lower().replace(" ", "_")
    path = os.path.join("tailored_resumes", company_slug, title_slug)
    
    if os.path.exists(path) and "--force" not in sys.argv:
        try:
            with open(os.path.join(path, "metadata.json"), "r") as f:
                meta = json.load(f).get("metadata", {})
            if meta.get("source_hash") == current_hash:
                logger.info(f"Skipping {title} @ {company} - valid cache exists at {path}/. Use --force to override.")
                sys.exit(0)
            else:
                logger.info(f"Cache miss: source experience has changed. Re-running.")
        except Exception:
            pass

    tailored_data = gemini.tailor_experience(jd, tailor.exp_json)
    if tailored_data.metadata:
        tailored_data.metadata.source_hash = current_hash
        
    final_tex = latex.populate(tailored_data, tailor.exp_json)
    tailor.save_outputs(path, tailored_data, final_tex)

if __name__ == "__main__":
    main()
