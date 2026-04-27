import re
import subprocess
import tempfile
import os
import math
from typing import Dict
from loguru import logger
from .models import TailoredResumeJSON

# ──────────────────────────────────────────────────────────────────
# Layout constants derived from resume_template.tex
#
# Template:  letterpaper (11×8.5in), 11pt, fullpage package
# Margins:   oddsidemargin -0.5in, textwidth +1in,
#            topmargin -0.5in, textheight +1.0in
# Result:    text width ≈ 7.5in (540pt), text height ≈ 10in (720pt)
#
# Bullets use \small (~10pt) inside a 0.97\textwidth tabular
# with an itemize indent of ~25pt.
# Bullet text width ≈ 0.97 × 540 - 25 ≈ 499pt
# At Computer Modern 10pt, avg char width ≈ 5.2pt → ~95 chars/line
# Each line takes ~12pt vertical space (baselineskip at \small)
# ──────────────────────────────────────────────────────────────────
CHARS_PER_LINE = 95
LINE_HEIGHT_PT = 12.0
PAGE_HEIGHT_PT = 720.0  # Available vertical space (textheight)

# Fixed vertical costs (in points) for non-bullet template elements.
# These values are derived from the template's \vspace commands,
# section formatting, and measured against compiled output.
HEADER_PT = 40          # Name + contact line + hrule
SECTION_TITLE_PT = 16   # Each \section{} heading (with vspace -4pt, -5pt)
EDU_ENTRY_PT = 24       # \resumeSubheading: 2-row tabular + vspace(-7pt)
EXP_HEADER_PT = 24      # \resumeSubheading: 2-row tabular + vspace(-7pt)
PROJECT_HEADER_PT = 18  # \resumeProjectHeading: 1-row tabular + vspace(-7pt)
ITEMIZE_OVERHEAD_PT = 6 # \begin/\end{itemize} + vspace(-5pt)
BULLET_VSPACE_PT = -2   # Each \resumeItem has vspace(-2pt)
SKILLS_BLOCK_PT = 30    # Skills section (static content, ~2–3 lines)

NUM_SECTIONS = 4        # Education, Experience, Projects, Technical Skills


class LaTeXEngine:
    def __init__(self, template: str):
        self.template = template
        self.lat_chars = {'&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\^{}', '\\': r'\textbackslash{}', '<': r'\textless{}', '>': r'\textgreater{}'}

    def escape(self, text: str) -> str:
        if not isinstance(text, str): return text
        regex = re.compile('|'.join(re.escape(str(key)) for key in sorted(self.lat_chars.keys(), key=lambda i: -len(i))))
        return regex.sub(lambda m: self.lat_chars[m.group()], text)

    def populate(self, tailored_data: TailoredResumeJSON, original_json: Dict) -> str:
        tex = self.template
        
        c = original_json.get('contact', {})
        # Replace specific known placeholders first
        # Note: URLs in \href should NOT be escaped for things like underscores
        placeholders = {
            'NAME': True,
            'LOCATION': True,
            'EMAIL': False,  # False means don't escape for URL usage
            'PHONE': True,
            'LINKEDIN': False,
            'GITHUB': False,
            'PORTFOLIO': False
        }
        for p, should_escape in placeholders.items():
            val = c.get(p.lower(), "")
            escaped_val = self.escape(val) if should_escape else val
            
            # Special case: The template uses {{EMAIL}} both inside \href and as display text
            # We'll just replace them. If we want to be perfect, we'd have separate tags.
            # For now, let's just not escape underscores in the main replacement if it's a URL field.
            tex = tex.replace(f"{{{{{p}}}}}", escaped_val)
        
        # Also replace any other keys present in contact
        for k, v in c.items():
            if k.upper() not in placeholders:
                tex = tex.replace(f"{{{{{k.upper()}}}}}", self.escape(v))
        
        edu_tex = ""
        for edu in original_json['education']:
            edu_tex += f"\\resumeSubheading{{{self.escape(edu['institution'])}}}{{{self.escape(edu['location'])}}}{{{self.escape(edu['degree'])}}}{{{self.escape(edu['dates'])}}}\n"
        tex = tex.replace("{{EDUCATION}}", edu_tex)

        exp_tex = ""
        for exp in tailored_data.experience:
            exp_tex += f"\\resumeSubheading{{{self.escape(exp.company)}}}{{{self.escape(exp.location)}}}{{{self.escape(exp.role)}}}{{{self.escape(exp.dates)}}}\n\\resumeItemListStart\n"
            for b in exp.bullets:
                exp_tex += f"  \\resumeItem{{{self.escape(b.tailored)}}}\n"
            exp_tex += "\\resumeItemListEnd\n"
        tex = tex.replace("{{EXPERIENCE}}", exp_tex)

        proj_tex = ""
        for prj in tailored_data.projects:
            proj_tex += f"\\resumeProjectHeading{{\\textbf{{{self.escape(prj.name)}}}}}{{{self.escape(prj.role)}}}\n\\resumeItemListStart\n"
            for b in prj.bullets:
                proj_tex += f"  \\resumeItem{{{self.escape(b.tailored)}}}\n"
            proj_tex += "\\resumeItemListEnd\n"
        tex = tex.replace("{{PROJECTS}}", proj_tex)

        skills_tex = ""
        for cat, items in original_json['skills'].items():
            skills_tex += f"\\textbf{{{self.escape(cat)}}}: {{{', '.join([self.escape(i) for i in items])}}} \\\\ \n"
        tex = tex.replace("{{SKILLS}}", skills_tex)

        return tex

    @staticmethod
    def estimate_page_fill(tailored_data: TailoredResumeJSON, source_data: dict) -> float:
        """
        Estimate how full the page will be (0.0 = empty, 1.0 = exactly full, >1.0 = overflow).

        Uses the template's known layout constants to calculate vertical space
        consumed by each element. Since the template is fixed (same fonts,
        margins, spacing), this is mechanically deterministic.
        """
        used_pt = 0.0

        # Fixed overhead
        used_pt += HEADER_PT
        used_pt += NUM_SECTIONS * SECTION_TITLE_PT
        used_pt += SKILLS_BLOCK_PT

        # Education entries (static — not modified by the LLM)
        education = source_data.get('education', [])
        if isinstance(education, dict):
            education = [education]
        used_pt += len(education) * EDU_ENTRY_PT

        # Experience entries
        for exp in tailored_data.experience:
            used_pt += EXP_HEADER_PT       # Company/role/dates header
            used_pt += ITEMIZE_OVERHEAD_PT  # Bullet list wrapper
            for b in exp.bullets:
                lines = math.ceil(len(b.tailored) / CHARS_PER_LINE)
                used_pt += lines * LINE_HEIGHT_PT + BULLET_VSPACE_PT

        # Project entries
        for prj in tailored_data.projects:
            used_pt += PROJECT_HEADER_PT
            used_pt += ITEMIZE_OVERHEAD_PT
            for b in prj.bullets:
                lines = math.ceil(len(b.tailored) / CHARS_PER_LINE)
                used_pt += lines * LINE_HEIGHT_PT + BULLET_VSPACE_PT

        return used_pt / PAGE_HEIGHT_PT

    def to_pdf(self, tex_code: str) -> tuple[bytes, int]:
        """
        Compile LaTeX source to PDF using tectonic.
        Returns (pdf_bytes, page_count) so the caller can verify the resume fits on one page.
        """
        logger.info("Compiling LaTeX → PDF via tectonic...")

        # Tectonic uses XeTeX internally, which doesn't have pdfTeX-only primitives.
        # Strip them out — tectonic already produces unicode-aware, ATS-parsable PDFs.
        tex_code = re.sub(r'\\input\{glyphtounicode\}', '% (stripped for tectonic)', tex_code)
        tex_code = re.sub(r'\\pdfgentounicode\s*=\s*1', '% (stripped for tectonic)', tex_code)

        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "resume.tex")
            pdf_path = os.path.join(tmpdir, "resume.pdf")

            with open(tex_path, "w") as f:
                f.write(tex_code)

            result = subprocess.run(
                ["tectonic", "-X", "compile", tex_path],
                capture_output=True, text=True, timeout=60
            )

            if result.returncode != 0:
                error_lines = [l for l in result.stderr.splitlines() if l.strip()]
                error_msg = "\n".join(error_lines[-10:]) if error_lines else result.stdout[-500:]
                logger.error(f"tectonic compilation failed:\n{error_msg}")
                raise RuntimeError(f"LaTeX compilation error:\n{error_msg}")

            if not os.path.exists(pdf_path):
                raise RuntimeError("tectonic ran but no PDF was produced. Check your .tex template for errors.")

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            # Extract page count using pypdf
            page_count = 1
            try:
                from pypdf import PdfReader
                import io
                reader = PdfReader(io.BytesIO(pdf_bytes))
                page_count = len(reader.pages)
            except Exception:
                pass

            if page_count > 1:
                logger.warning(f"⚠️ Resume compiled to {page_count} pages — should be 1 page!")
            else:
                logger.success(f"PDF compiled successfully — {page_count} page, {len(pdf_bytes):,} bytes.")

            return pdf_bytes, page_count
