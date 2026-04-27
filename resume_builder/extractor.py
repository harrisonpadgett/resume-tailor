import json
import re
from loguru import logger
from .llm import GeminiTailor

class ResumeExtractor:
    def __init__(self, tailor: GeminiTailor):
        self.tailor = tailor

    def extract_from_tex(self, tex_content: str) -> dict:
        prompt = f"""Extract the resume information from the following LaTeX source code and output it strictly in the JSON format provided below. Do not miss any bullet points or details. If a section is missing from the LaTeX file, leave the array empty.

=== LATEX SOURCE ===
{tex_content}

=== OUTPUT FORMAT ===
{{
  "contact": {{
    "name": "...",
    "phone": "...",
    "email": "...",
    "location": "...",
    "linkedin": "...",
    "github": "...",
    "portfolio": "..."
  }},
  "education": [
    {{
      "institution": "...",
      "location": "...",
      "degree": "...",
      "dates": "..."
    }}
  ],
  "experience": [
    {{
      "company": "...",
      "role": "...",
      "dates": "...",
      "location": "...",
      "bullets": [
        {{
          "original": "...",
          "tailored": "...",
          "rationale": "No change"
        }}
      ]
    }}
  ],
  "projects": [
    {{
      "name": "...",
      "role": "...",
      "bullets": [
        {{
          "original": "...",
          "tailored": "...",
          "rationale": "No change"
        }}
      ]
    }}
  ],
  "skills": {{
    "Languages": ["..."],
    "Frameworks": ["..."],
    "Developer Tools": ["..."],
    "Libraries": ["..."]
  }}
}}

RULES:
- For bullets, put the EXACT extracted text into BOTH the 'original' and 'tailored' fields.
- Make sure to extract all bullet points for experiences and projects.
- Respond ONLY with valid JSON. Do not include markdown formatting or commentary.
"""
        response_text = None
        # _reliable_generate yields log/result events; consume it to get the final text
        for event in self.tailor._reliable_generate(prompt):
          if "log" in event:
            logger.info(event["log"])
          elif "result" in event:
            response_text = event["result"]
            break

        if response_text is None:
          raise ValueError("LLM did not return any text for extraction.")

        clean_json = re.sub(r'```json\s*|```', '', response_text).strip()
        try:
            data = json.loads(clean_json)
            
            # Validate that we actually found some content
            has_experience = len(data.get("experience", [])) > 0
            has_projects = len(data.get("projects", [])) > 0
            has_education = len(data.get("education", [])) > 0
            
            if not has_experience and not has_projects and not has_education:
                raise ValueError("Could not find any resume content (Experience, Projects, or Education) in the uploaded file. Please ensure it's a valid LaTeX resume.")
                
            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode extracted JSON: {e}\nRaw Response:\n{clean_json}")
            raise ValueError("Could not parse the extracted resume information. Please try again.")
