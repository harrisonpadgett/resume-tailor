import re
from typing import Dict
from .models import TailoredResumeJSON

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
        
        c = original_json['contact']
        for k, v in c.items(): tex = tex.replace(f"{{{{{k.upper()}}}}}", self.escape(v))
        
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
