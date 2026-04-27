import json
import os
from loguru import logger
from .models import TailoredResumeJSON

class ResumeTailor:
    def __init__(self, experience_file: str, template_file: str):
        with open(experience_file, 'r') as f: self.exp_json = json.load(f)
        with open(template_file, 'r') as f: self.template = f.read()

    def save_outputs(self, path: str, data: TailoredResumeJSON, tex: str):
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "metadata.json"), "w") as f: f.write(data.model_dump_json(indent=2))
        with open(os.path.join(path, "resume.tex"), "w") as f: f.write(tex)
        with open(os.path.join(path, "rationale.txt"), "w") as f:
            f.write(f"--- RATIONALE FOR CACHE ---\n\n")
            for exp in data.experience:
                f.write(f"[{exp.company}]\n")
                for b in exp.bullets:
                    f.write(f"Original: {b.original}\nTailored: {b.tailored}\nRationale: {b.rationale}\n\n")
            for prj in data.projects:
                f.write(f"[{prj.name}]\n")
                for b in prj.bullets:
                    f.write(f"Original: {b.original}\nTailored: {b.tailored}\nRationale: {b.rationale}\n\n")
                    
        logger.success(f"Tailored resume saved to {path}/")
