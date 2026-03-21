# Resume Tailor

ATS keyword injection pipeline for resumes. Takes a job posting URL, extracts keywords from the description, and injects them into resume bullet points using Gemini. Outputs a compile-ready LaTeX file.

## Requirements

- Python 3.10+
- Gemini API key ([get one here](https://aistudio.google.com/app/apikey))

## Setup

```bash
pip install streamlit loguru pydantic beautifulsoup4 requests sentence-transformers google-genai python-dotenv trafilatura tldextract playwright
playwright install chromium
```

Create a `.env` file:
```
GEMINI_API_KEY=your_key
```

Provide two data files in the project root:
- `experience.json` — structured resume data (contact, education, experience, projects, skills)
- `resume_template.tex` — LaTeX template with `{{PLACEHOLDER}}` tokens

## Usage

### Web UI
```bash
streamlit run app.py
```

### CLI
```bash
python tailor_resume.py "https://boards.greenhouse.io/company/jobs/12345"
python tailor_resume.py "https://boards.greenhouse.io/company/jobs/12345" --force
```

The `--force` flag bypasses the local cache and runs a fresh API call.

## How It Works

1. **Scrape** — Extracts job description text from the URL using a 3-tier fallback: Trafilatura → BeautifulSoup → Playwright (headless Chromium for bot-protected sites).
2. **Extract** — Gemini extracts up to 30 keywords that literally appear in the job description.
3. **Inject** — Gemini injects extracted keywords into resume bullets via synonym swaps or natural insertions. Quantitative metrics are never modified.
4. **Guard** — A rule-based hallucination guard rejects bullets that contain fabricated metrics, inflated verbs, or injected technologies not present in the original.
5. **Render** — Tailored bullets are inserted into the LaTeX template alongside untouched contact, education, and skills sections.
6. **Cache** — Results are saved to `tailored_resumes/{company}/{role}/`. Subsequent runs for the same job skip the API call unless the resume data has changed.

## Project Structure

```
keywords/
├── app.py                  # Streamlit dashboard
├── tailor_resume.py        # CLI entry point
├── experience.json         # Resume source data
├── resume_template.tex     # LaTeX template
├── resume_builder/
│   ├── models.py           # Pydantic schemas
│   ├── scraper.py          # URL scraping + company extraction
│   ├── llm.py              # Gemini prompt + system instruction
│   ├── guard.py            # Hallucination guard
│   ├── latex.py            # LaTeX escaping + template population
│   └── tailor.py           # File I/O + output saving
└── tailored_resumes/       # Cached outputs by company/role
```

## Supported Job Board URLs

Greenhouse, Lever, Workday (`myworkdayjobs.com`, `myworkdaysite.com`), SmartRecruiters, Ashby, BambooHR, Eightfold, iCIMS, and any direct company career page. Bot-protected sites (e.g. Cloudflare-guarded pages) are handled by the Playwright fallback.