import re
import subprocess
import tempfile
import os
from typing import Dict
from loguru import logger
from .models import TailoredResumeJSON

# Layout constants calibrated to resume_template.tex
# (letterpaper, 11pt, fullpage pkg; effective text area ≈7.5in × 10in)
CHARS_PER_LINE = 95
LINE_HEIGHT_PT = 12.0
PAGE_HEIGHT_PT = 720.0

HEADER_PT = 40
SECTION_TITLE_PT = 16
EDU_ENTRY_PT = 24
EXP_HEADER_PT = 24
PROJECT_HEADER_PT = 18
ITEMIZE_OVERHEAD_PT = 6
BULLET_VSPACE_PT = -2
SKILLS_BLOCK_PT = 30
NUM_SECTIONS = 4

_LATEX_CHARS = {
    '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
    '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\^{}',
    '\\': r'\textbackslash{}', '<': r'\textless{}', '>': r'\textgreater{}',
}
_LATEX_ESCAPE_RE = re.compile(
    '|'.join(re.escape(k) for k in sorted(_LATEX_CHARS, key=len, reverse=True))
)

_CONTACT_FIELDS = ['name', 'location', 'email', 'phone', 'linkedin', 'github', 'portfolio']
# These fields appear inside \href{} commands — underscores must not be escaped
_URL_FIELDS = {'email', 'linkedin', 'github', 'portfolio'}


class LaTeXEngine:
    def __init__(self, template: str):
        self.template = template

    def escape(self, text: str) -> str:
        if not isinstance(text, str):
            return text
        return _LATEX_ESCAPE_RE.sub(lambda m: _LATEX_CHARS[m.group()], text)

    def populate(self, tailored_data: TailoredResumeJSON, original_json: Dict) -> str:
        tex = self.template
        c = original_json.get('contact', {})

        for key in _CONTACT_FIELDS:
            val = c.get(key, "")
            escaped = val if key in _URL_FIELDS else self.escape(val)
            tex = tex.replace(f"{{{{{key.upper()}}}}}", escaped)

        edu_tex = ""
        for edu in original_json['education']:
            edu_tex += (
                f"\\resumeSubheading"
                f"{{{self.escape(edu['institution'])}}}{{{self.escape(edu['location'])}}}"
                f"{{{self.escape(edu['degree'])}}}{{{self.escape(edu['dates'])}}}\n"
            )
        tex = tex.replace("{{EDUCATION}}", edu_tex)

        exp_tex = ""
        for exp in tailored_data.experience:
            exp_tex += (
                f"\\resumeSubheading"
                f"{{{self.escape(exp.company)}}}{{{self.escape(exp.location)}}}"
                f"{{{self.escape(exp.role)}}}{{{self.escape(exp.dates)}}}\n"
                f"\\resumeItemListStart\n"
            )
            for b in exp.bullets:
                exp_tex += f"  \\resumeItem{{{self.escape(b.tailored)}}}\n"
            exp_tex += "\\resumeItemListEnd\n"
        tex = tex.replace("{{EXPERIENCE}}", exp_tex)

        proj_tex = ""
        for prj in tailored_data.projects:
            proj_tex += (
                f"\\resumeProjectHeading{{\\textbf{{{self.escape(prj.name)}}}}}"
                f"{{{self.escape(prj.role)}}}\n"
                f"\\resumeItemListStart\n"
            )
            for b in prj.bullets:
                proj_tex += f"  \\resumeItem{{{self.escape(b.tailored)}}}\n"
            proj_tex += "\\resumeItemListEnd\n"
        tex = tex.replace("{{PROJECTS}}", proj_tex)

        skills_tex = ""
        for cat, items in original_json['skills'].items():
            skills_tex += f"\\textbf{{{self.escape(cat)}}}: {{{', '.join(self.escape(i) for i in items)}}} \\\\ \n"
        tex = tex.replace("{{SKILLS}}", skills_tex)

        return tex

    def to_pdf(self, tex_code: str) -> tuple[bytes, int]:
        """Compile LaTeX to PDF via tectonic. Returns (pdf_bytes, page_count)."""
        logger.info("Compiling LaTeX → PDF via tectonic...")

        # Strip pdfTeX-only primitives; tectonic uses XeTeX internally
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
                raise RuntimeError("tectonic ran but no PDF was produced.")

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

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
