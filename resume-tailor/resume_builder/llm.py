import json
import re
from typing import Dict, Optional
from loguru import logger
from google import genai
from google.genai import types
from .models import TailoredResumeJSON, ATSReport
from .guard import HallucinationGuard

# System instruction — sent once per model config, not repeated in every prompt.
# Gemini treats this as a persistent behavioral contract with higher priority than user content.
SYSTEM_INSTRUCTION = """You are a keyword-injection engine for ATS resume optimization.

RULES (in priority order):
1. NEVER remove or change any number, metric, percentage, dollar amount, or quantitative result. These are sacred. "Reduced latency by 40%" must stay exactly "Reduced latency by 40%".
2. ONLY modify bullets by swapping or inserting JD keywords. Do NOT rewrite sentences or change formatting.
3. Do NOT add technologies, tools, or achievements that are not already present in the original bullet.
4. Keep the original sentence structure. Minimal edits only — swap a synonym for a JD keyword, or append a relevant keyword where natural.
5. Injected keywords MUST read grammatically in context (e.g. "Built REST API" not "Built REST API Angular"). Do NOT fix any other grammar or phrasing in the original bullet.
6. Bullet length must stay similar to the original. Do not significantly shorten or lengthen bullets.
7. If a bullet cannot naturally incorporate any JD keywords, return it unchanged.

KEYWORD EXTRACTION RULES:
- Only extract terms that literally appear in the JD text: programming languages, frameworks, tools, databases, methodologies, certifications, and domain-specific terms.
- Do NOT infer or generalize — if the JD says "PostgreSQL", extract "PostgreSQL", not "databases".

OUTPUT RULES:
- Every 'experience' entry MUST include: company, role, dates, location, bullets.
- Every 'projects' entry MUST include: name, role, bullets.
- Each bullet must be an object with: 'original', 'tailored', 'rationale'.
- In 'rationale', state which keyword(s) were injected, or say "No change" if left as-is.
- Respond ONLY with valid JSON. No markdown fences, no commentary.
"""

class GeminiTailor:
    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)
        self.model_id = 'gemini-2.0-flash-lite'

    MODEL_CHAIN = [
        'gemini-2.0-flash-lite',
        'gemini-2.0-flash',
        'gemini-2.5-flash',
    ]

    def _reliable_generate(self, prompt: str) -> any:
        exhausted = []
        for model in self.MODEL_CHAIN:
            try:
                res = self.client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTION,
                    ),
                )
                if exhausted:
                    logger.info(f"Succeeded using fallback model: {model} (exhausted: {exhausted})")
                return res
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    logger.warning(f"[QUOTA] '{model}' daily limit reached, trying next model...")
                    exhausted.append(model)
                    continue
                raise e
        
        exhausted_str = ', '.join(exhausted)
        raise RuntimeError(
            f"ALL_QUOTA_EXHAUSTED|{exhausted_str}|All Gemini models have exhausted their daily free quota. "
            f"Models tried: {exhausted_str}. Please wait for the daily reset (~midnight PT) or upgrade to a paid API key."
        )

    def tailor_experience(self, jd: str, experience_data: Dict) -> TailoredResumeJSON:
        if not jd: jd = "Generic Role"
        logger.info("Single-pass AI: Analyzing JD and keyword-injecting in one call...")
        
        combined_prompt = f"""Extract up to 30 keywords from the JD below, then inject them into the resume bullets.

=== JOB DESCRIPTION (JD) ===
{jd[:3000]}

=== RESUME CONTEXT (JSON) ===
{json.dumps(experience_data, indent=2)}

=== OUTPUT FORMAT ===
{{
  "metadata": {{
    "keywords": ["...", "..."]
  }},
  "experience": [ {{ "company": "...", "role": "...", "dates": "...", "location": "...", "bullets": [{{"original":"...","tailored":"...","rationale":"..."}}] }} ],
  "projects": [ {{ "name": "...", "role": "...", "bullets": [{{"original":"...","tailored":"...","rationale":"..."}}] }} ]
}}
"""
        
        response = self._reliable_generate(combined_prompt)
        clean_json = re.sub(r'```json\s*|```', '', response.text).strip()
        data = json.loads(clean_json)
        
        jd_meta = data.pop('metadata', {})
        target_keywords = jd_meta.get('keywords', [])
        
        tailored_resume = TailoredResumeJSON(**data)
        
        all_text_parts = []
        for exp in tailored_resume.experience:
            for b in exp.bullets:
                all_text_parts.append(b.tailored)
        for prj in tailored_resume.projects:
            for b in prj.bullets:
                all_text_parts.append(b.tailored)
        skills = experience_data.get('skills', {})
        for cat, items in skills.items():
            if isinstance(items, list):
                all_text_parts.extend(items)
            else:
                all_text_parts.append(str(items))
        all_text_combined = " ".join(all_text_parts)
        
        def keyword_in_text(keyword, text):
            escaped = re.escape(keyword)
            pattern = r'(?<![a-zA-Z])' + escaped + r'(?![a-zA-Z+#])'
            return bool(re.search(pattern, text, re.IGNORECASE))
        
        found_keywords = [k for k in target_keywords if keyword_in_text(k, all_text_combined)]
        missing_keywords = [k for k in target_keywords if not keyword_in_text(k, all_text_combined)]
        
        tailored_resume.metadata = ATSReport(
            target_keywords=target_keywords,
            found_keywords=found_keywords,
            missing_keywords=missing_keywords,
            total_score=round((len(found_keywords) / len(target_keywords)) * 100, 2) if target_keywords else 0.0
        )

        for exp in tailored_resume.experience:
            exp.bullets = exp.bullets[:4] 
            for b in exp.bullets:
                if not HallucinationGuard.verify(b.original, b.tailored, target_keywords=target_keywords):
                    logger.warning(f"Reverting bullet due to hallucination suspicion: {b.tailored[:50]}...")
                    b.rationale = "⚠️ REJECTED: " + b.rationale + " (Failed hallucination check)"
                    b.tailored = b.original 
        
        for prj in tailored_resume.projects:
            prj.bullets = prj.bullets[:3] 
            for b in prj.bullets:
                if not HallucinationGuard.verify(b.original, b.tailored, target_keywords=target_keywords):
                    b.rationale = "⚠️ REJECTED: " + b.rationale + " (Failed hallucination check)"
                    b.tailored = b.original
        
        return tailored_resume
