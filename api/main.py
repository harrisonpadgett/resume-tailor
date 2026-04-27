from fastapi import FastAPI, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
import json
import os
import tempfile
import subprocess
import hashlib
from dotenv import load_dotenv
from loguru import logger

# Setup file logging
logger.add("api.log", rotation="10 MB", level="INFO")

from resume_builder.llm import GeminiTailor
from resume_builder.extractor import ResumeExtractor
from resume_builder.scraper import JobScraper
from resume_builder.latex import LaTeXEngine

load_dotenv()

app = FastAPI(title="Resume Tailor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY is not set")

gemini = GeminiTailor(api_key)
extractor = ResumeExtractor(gemini)

class TailorRequest(BaseModel):
    job_target: str = ""
    job_text: str = ""
    source_data: dict
    resume_template: str
    force_run: bool = False

@app.post("/api/extract")
async def extract_resume(file: UploadFile = File(...)):
    logger.info(f"Extracting uploaded file: {file.filename}")
    if not file.filename.endswith(".tex"):
        logger.error("Uploaded file is not a .tex file.")
        raise HTTPException(status_code=400, detail="Must be a .tex file")
    
    content = await file.read()
    try:
        tex_content = content.decode("utf-8")
        source_data = extractor.extract_from_tex(tex_content)
        with open("resume_template.tex", "r") as f:
            resume_template = f.read()
        logger.success("Successfully extracted source data.")
        return {"source_data": source_data, "resume_template": resume_template}
    except Exception as e:
        logger.exception("Extraction failed")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/sample")
async def get_sample():
    try:
        with open("experience.json", "r") as f:
            source_data = json.load(f)
        with open("resume_template.tex", "r") as f:
            resume_template = f.read()
        return {
            "source_data": source_data,
            "resume_template": resume_template
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load sample data: {str(e)}")

from fastapi.responses import StreamingResponse

@app.post("/api/tailor")
def tailor_resume(request: TailorRequest):
    if not (request.job_target or request.job_text):
        raise HTTPException(status_code=400, detail="Please provide a Job URL or Description.")
    
    def event_stream():
        try:
            yield json.dumps({"log": "Scraping job description..."}) + "\n"
            if request.job_target and not request.job_text:
                company, title, jd_content = JobScraper.get_job_info(request.job_target, gemini_model=gemini.client)
            else:
                company, title, jd_content = JobScraper.get_job_info(request.job_text, gemini_model=gemini.client)
                
            if not jd_content:
                yield json.dumps({"error": "Could not scrape job description. Please paste text directly."}) + "\n"
                return

            yield json.dumps({"log": f"Analyzing {title} @ {company}..."}) + "\n"

            # Cache check
            current_source_hash = hashlib.md5(json.dumps(request.source_data, sort_keys=True).encode()).hexdigest()
            path = os.path.join("tailored_resumes", company.lower().replace(" ", "_"), title.lower().replace(" ", "_"))
            
            res_json = None
            res_tex = None
            is_cached = False
            
            if request.force_run:
                yield json.dumps({"log": "Cache bypassed: Force rerun enabled."}) + "\n"
            elif not os.path.exists(path):
                yield json.dumps({"log": "Cache miss: No previous run found for this job."}) + "\n"
            else:
                try:
                    with open(os.path.join(path, "metadata.json"), "r") as f:
                        res_json = json.load(f)
                    
                    has_fallback = any("FALLBACK" in b.get('rationale', '') for exp in res_json.get('experience', []) for b in exp.get('bullets', []))
                    cached_source_hash = res_json.get('metadata', {}).get('source_hash')
                    
                    if has_fallback:
                        yield json.dumps({"log": "Cache invalidated: Previous AI run contained fallback logic."}) + "\n"
                    elif cached_source_hash != current_source_hash:
                        yield json.dumps({"log": "Cache invalidated: Base resume data was modified."}) + "\n"
                    else:
                        yield json.dumps({"log": "Cache hit: Loading previously tailored resume..."}) + "\n"
                        with open(os.path.join(path, "resume.tex"), "r") as f:
                            res_tex = f.read()
                        is_cached = True
                except:
                    yield json.dumps({"log": "Cache error: Failed to read cache files."}) + "\n"

            if not is_cached:
                target_keywords = None
                for event in gemini.extract_keywords(jd_content):
                    if "log" in event:
                        yield json.dumps({"log": event["log"]}) + "\n"
                    elif "result" in event:
                        target_keywords = event["result"]
                
                yield json.dumps({"log": f"Model Used (Pass 1): {gemini.last_used_model}"}) + "\n"
                yield json.dumps({"log": f"Target keywords: {', '.join(target_keywords)}"}) + "\n"
                
                latex = LaTeXEngine(request.resume_template)
                res_obj = None
                for event in gemini.tailor_experience(jd_content, request.source_data, target_keywords):
                    if "log" in event:
                        yield json.dumps({"log": event["log"]}) + "\n"
                    elif "result" in event:
                        res_obj = event["result"]
                        
                yield json.dumps({"log": f"Model Used (Pass 2): {gemini.last_used_model}"}) + "\n"
                
                # --- Enforce 1-Page Limit ---
                yield json.dumps({"log": "Verifying compiled page length..."}) + "\n"
                res_tex = latex.populate(res_obj, request.source_data)
                
                try:
                    _, page_count = latex.to_pdf(res_tex)
                    if page_count > 1:
                        yield json.dumps({"log": f"Length Warning: Resume compiled to {page_count} pages. Auto-truncating..."}) + "\n"
                        
                        while page_count > 1:
                            # Strategy: Drop the last bullet of the oldest project, then oldest experience
                            dropped = False
                            if res_obj.projects:
                                for i in range(len(res_obj.projects) - 1, -1, -1):
                                    if res_obj.projects[i].bullets:
                                        res_obj.projects[i].bullets.pop()
                                        dropped = True
                                        break
                                        
                            if not dropped and res_obj.experience:
                                for i in range(len(res_obj.experience) - 1, -1, -1):
                                    if len(res_obj.experience[i].bullets) > 1: # Try to keep at least 1 bullet per job
                                        res_obj.experience[i].bullets.pop()
                                        dropped = True
                                        break
                                        
                            if not dropped:
                                break # Safety escape
                                
                            res_tex = latex.populate(res_obj, request.source_data)
                            _, page_count = latex.to_pdf(res_tex)
                            
                        yield json.dumps({"log": "Truncation complete. Resume fits perfectly on 1 page."}) + "\n"
                except Exception as e:
                    yield json.dumps({"log": f"Warning: Could not verify page length. {str(e)}"}) + "\n"
                # ----------------------------
                
                if res_obj.metadata:
                    res_obj.metadata.source_hash = current_source_hash
                
                yield json.dumps({"log": "Finalizing LaTeX output..."}) + "\n"
                res_tex = latex.populate(res_obj, request.source_data)
                res_json = res_obj.model_dump()
                
                # Save cache
                os.makedirs(path, exist_ok=True)
                with open(os.path.join(path, "metadata.json"), "w") as f:
                    json.dump(res_json, f, indent=2)
                with open(os.path.join(path, "resume.tex"), "w") as f:
                    f.write(res_tex)
                    
            # Extract keywords from LLM metadata
            meta = res_json.get('metadata', {})
            target_kws = meta.get('target_keywords', [])
            found_kws = meta.get('found_keywords', [])
            added_kws = meta.get('added_keywords', [])
            missing_kws = meta.get('missing_keywords', [])
            
            if not is_cached:
                yield json.dumps({"log": f"Audit complete. Found: {len(found_kws)}, Added: {len(added_kws)}, Missing: {len(missing_kws)}"}) + "\n"

            logger.success(f"Tailoring complete for {title} @ {company}.")
            yield json.dumps({
                "result": {
                    "company": company,
                    "title": title,
                    "jd_content": jd_content,
                    "res_json": res_json,
                    "res_tex": res_tex,
                    "found_keywords": found_kws,
                    "added_keywords": added_kws,
                    "missing_keywords": missing_kws,
                    "target_keywords": target_kws
                }
            }) + "\n"
        except Exception as e:
            logger.exception("Tailoring failed")
            err_msg = str(e)
            if err_msg.startswith("ALL_QUOTA_EXHAUSTED"):
                yield json.dumps({"error": "All AI models are currently rate-limited. Wait a few minutes and try again."}) + "\n"
            else:
                yield json.dumps({"error": f"Pipeline Error: {err_msg}"}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")

class CompileRequest(BaseModel):
    tex_content: str

@app.post("/api/compile")
async def compile_resume(request: CompileRequest):
    try:
        with tempfile.TemporaryDirectory() as td:
            tex_path = os.path.join(td, "resume.tex")
            with open(tex_path, "w") as f:
                f.write(request.tex_content)
            
            result = subprocess.run(["tectonic", tex_path], capture_output=True, text=True, cwd=td)
            if result.returncode != 0:
                raise Exception(f"Tectonic failed: {result.stderr}")
            
            pdf_path = os.path.join(td, "resume.pdf")
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
                
            return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
