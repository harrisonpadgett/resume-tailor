import json
import re
from typing import Dict
from loguru import logger
from openai import OpenAI
from .models import TailoredResumeJSON, ATSReport
from .guard import HallucinationGuard

SYSTEM_INSTRUCTION = """You are a keyword-injection engine for ATS resume optimization.

RULES (in priority order):
1. NEVER remove or change any number, metric, percentage, dollar amount, or quantitative result. These are sacred. "Reduced latency by 40%" must stay exactly "Reduced latency by 40%".
2. AGGRESSIVELY REPLACE synonymous concepts or wordy descriptions with the exact TARGET KEYWORDS. Prioritize keyword matching over preserving original wording. If the semantic meaning remains identical, swap out the candidate's phrasing for the JD's phrasing.
3. Do not hallucinate fake experience; do not add tools or achievements the candidate does not have. However, you MUST map broader semantic JD keywords (e.g., "ML algorithms") to specific technologies already present in the bullet (e.g., "HDBSCAN clustering") by replacing them or combining them.
4. It is perfectly acceptable and heavily encouraged to shorten bullets if wordy concepts are replaced by precise target keywords.
5. Injected keywords MUST read grammatically in context. Adjust capitalization to fit the sentence structure (e.g., lowercase "software development" mid-sentence even if it was extracted as "Software Development"). Only use Title Case for proper nouns (e.g., "Python", "AWS").
6. NEVER inject the same keyword more than 2 times across the ENTIRE resume. Avoid keyword stuffing. Distribute different keywords naturally.
7. If a bullet cannot naturally incorporate any new JD keywords, return it unchanged.
8. Do NOT use markdown bolding or asterisks (**) around injected keywords. Output raw plain text only.

KEYWORD EXTRACTION RULES:
- Extract ONLY concrete, ATS-scannable terms: programming languages, frameworks, libraries, tools, platforms, databases, cloud services, methodologies (e.g. "Agile", "Scrum", "CI/CD"), certifications, specific domain terms (e.g. "NLP", "computer vision"), and established role descriptors (e.g. "full-stack", "DevOps").
- Extract compound technical phrases as single keywords when they form a recognized term: "machine learning", "agentic AI", "large language models", "data engineering", "CI/CD", etc.
- Do NOT extract generic verb phrases, soft-skill clauses, or vague JD filler. Examples of what to EXCLUDE: "engage directly with sponsors", "verbal and written", "data science fields", "work collaboratively", "fast-paced environment", "strong communication skills", "ability to manage", "passion for learning".
- Do NOT extract partial fragments of sentences or phrases longer than 4 words unless they are a recognized technical term (e.g. "large language models" is OK, "build and maintain data pipelines" is NOT — extract "data pipelines" instead).
- Do NOT infer or generalize — if the JD says "PostgreSQL", extract "PostgreSQL", not "databases".
- Aim for 20-40 high-quality keywords. Prefer precision over recall — every keyword should be something a resume scanner would actually match on.

OUTPUT RULES:
- Every 'experience' entry MUST include: company, role, dates, location, bullets.
- Every 'projects' entry MUST include: name, role, bullets.
- Each bullet must be an object with: 'original', 'tailored', 'rationale'.
- In 'rationale', state which keyword(s) were injected, or say "No change" if left as-is.
- Respond ONLY with valid JSON. No markdown fences, no commentary.
"""

_STOPWORD_PHRASES = {
    "verbal and written", "written and verbal", "strong communication",
    "fast-paced environment", "work collaboratively", "team environment",
    "attention to detail", "problem solving", "self-starter",
    "passion for", "ability to", "responsible for", "experience with",
    "knowledge of", "familiarity with", "understanding of",
    "excellent communication", "interpersonal skills", "organizational skills",
    "time management", "critical thinking", "detail-oriented",
}

_FILLER_VERBS = {
    "engage", "collaborate", "communicate", "manage", "develop",
    "maintain", "support", "assist", "ensure", "participate",
    "contribute", "provide", "work", "build", "create",
    "identify", "evaluate", "implement", "deliver", "demonstrate",
    "leverage", "drive", "lead", "oversee", "coordinate",
}

# OpenRouter free-tier models, ordered fastest-first
MODEL_CHAIN = [
    "google/gemma-4-26b-a4b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-3-27b-it:free",
    "openai/gpt-oss-20b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-3-12b-it:free",
]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class ResumeTailor:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)
        self.last_used_model: str | None = None

    @staticmethod
    def _filter_keywords(raw_keywords: list) -> list:
        filtered = []
        for kw in raw_keywords:
            kw_clean = kw.strip()
            if not kw_clean or len(kw_clean) < 2:
                continue
            kw_lower = kw_clean.lower()
            word_count = len(kw_clean.split())
            if word_count > 4:
                logger.debug(f"Keyword filtered (too long): '{kw_clean}'")
                continue
            if any(stop in kw_lower for stop in _STOPWORD_PHRASES):
                logger.debug(f"Keyword filtered (stopword): '{kw_clean}'")
                continue
            if word_count >= 3 and kw_clean.split()[0].lower() in _FILLER_VERBS:
                logger.debug(f"Keyword filtered (verb phrase): '{kw_clean}'")
                continue
            filtered.append(kw_clean)

        if len(raw_keywords) != len(filtered):
            logger.info(f"Keyword filter: {len(raw_keywords)} → {len(filtered)} (removed {len(raw_keywords) - len(filtered)} vague terms)")
        return filtered

    def _reliable_generate(self, prompt: str):
        """Try each model in MODEL_CHAIN in order, rotating on quota/rate errors.
        Yields {log: str} events during model rotation, then {result: str} on success."""
        exhausted = []
        self.last_used_model = None
        for model in MODEL_CHAIN:
            try:
                yield {"log": f"Trying model: {model}"}
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.3,
                    max_tokens=4000,
                    timeout=30,
                )
                text = response.choices[0].message.content

                if not text:
                    msg = response.choices[0].message
                    reasoning = getattr(msg, 'reasoning_content', None)
                    if reasoning:
                        text = reasoning
                    else:
                        yield {"log": f"[SKIP] '{model}' returned empty content, trying next..."}
                        exhausted.append(model)
                        continue

                if exhausted:
                    yield {"log": f"Succeeded with model: {model} (skipped: {len(exhausted)} models)"}
                self.last_used_model = model
                yield {"result": text}
                return
            except Exception as e:
                err_msg = str(e)
                if any(code in err_msg for code in ("429", "404", "400", "rate_limit", "overloaded", "503", "context_length", "timeout", "timed out", "ReadTimeout")):
                    yield {"log": f"[SKIP] Rate limited on '{model}'. Rotating to next model..."}
                    exhausted.append(model)
                    continue
                raise e

        exhausted_str = ", ".join(exhausted)
        raise RuntimeError(
            f"ALL_QUOTA_EXHAUSTED|{exhausted_str}|All OpenRouter free models are currently rate-limited or unavailable. "
            f"Models tried: {exhausted_str}. Wait a few minutes and try again, or add credits to your OpenRouter account."
        )

    def generate_text(self, prompt: str) -> str:
        """Run generation and return the result text, logging model rotation to logger."""
        for event in self._reliable_generate(prompt):
            if "log" in event:
                logger.info(event["log"])
            elif "result" in event:
                return event["result"]
        raise RuntimeError("LLM generation returned no result.")

    def extract_keywords(self, jd: str):
        if not jd:
            jd = "Generic Role"
        yield {"log": "Pass 1/2: Extracting optimal ATS keywords..."}

        prompt = f"""Extract 30-50 highly specific, ATS-relevant technical keywords from the job description below. Focus exclusively on hard skills, programming languages, databases, frameworks, libraries, tools, and concrete methodologies.
Do NOT include soft skills, vague phrases, or long sentences (e.g., exclude "fast-paced environment", "collaborative team", "verbal and written").
Crucially, do NOT group multiple keywords into a single string. "Python, Java, C++" is wrong. They must be separate array elements: "Python", "Java", "C++".

=== JOB DESCRIPTION ===
{jd[:3000]}

=== OUTPUT FORMAT ===
Return ONLY a valid JSON list of strings. Example: ["Python", "React", "AWS", "Agile", "SQL"]
"""
        raw_text = None
        for event in self._reliable_generate(prompt):
            if "log" in event:
                yield event
            elif "result" in event:
                raw_text = event["result"]

        clean_json = re.sub(r'```json\s*|```', '', raw_text).strip()
        try:
            raw_keywords = json.loads(clean_json)
        except Exception:
            raw_keywords = [k.strip().replace('"', '') for k in clean_json.split(',')]

        target_keywords = self._filter_keywords(raw_keywords)

        if not target_keywords:
            raise RuntimeError("NO_KEYWORDS_FOUND|No relevant technical keywords could be extracted from the job description.")

        yield {"log": f"Extracted {len(target_keywords)} target keywords."}
        yield {"result": target_keywords}

    def tailor_experience(self, jd: str, experience_data: Dict, target_keywords: list):
        yield {"log": "Pass 2/2: Tailoring resume bullets with injected keywords..."}

        prompt = f"""You are an expert resume writer. Inject the provided TARGET KEYWORDS naturally into the resume bullets. Follow the strict rules outlined in the system prompt. Do not hallucinate experience.

=== TARGET KEYWORDS TO INJECT ===
{", ".join(target_keywords)}

=== JOB DESCRIPTION CONTEXT ===
{jd[:3000]}

=== RESUME CONTEXT (JSON) ===
{json.dumps(experience_data, indent=2)}

=== OUTPUT FORMAT ===
{{
  "experience": [ {{ "company": "...", "role": "...", "dates": "...", "location": "...", "bullets": [{{"original":"...","tailored":"...","rationale":"..."}}] }} ],
  "projects": [ {{ "name": "...", "role": "...", "bullets": [{{"original":"...","tailored":"...","rationale":"..."}}] }} ]
}}
"""
        raw_text = None
        for event in self._reliable_generate(prompt):
            if "log" in event:
                yield event
            elif "result" in event:
                raw_text = event["result"]

        clean_json = re.sub(r'```json\s*|```', '', raw_text).strip()
        data = json.loads(clean_json)
        tailored_resume = TailoredResumeJSON(**data)

        def keyword_in_text(keyword, text):
            escaped = re.escape(keyword)
            pattern = r'(?<![a-zA-Z])' + escaped + r'(?![a-zA-Z+#])'
            return bool(re.search(pattern, text, re.IGNORECASE))

        orig_parts = []
        for exp in tailored_resume.experience:
            for b in exp.bullets:
                orig_parts.append(b.original)
        for prj in tailored_resume.projects:
            for b in prj.bullets:
                orig_parts.append(b.original)
        skills_flat = " ".join(
            item for items in experience_data.get('skills', {}).values()
            for item in (items if isinstance(items, list) else [items])
        )
        edu_flat = " ".join(
            str(v)
            for edu in (experience_data.get('education') if isinstance(experience_data.get('education'), list) else [experience_data.get('education', {})])
            for v in edu.values()
        )
        orig_full = " ".join(orig_parts + [skills_flat, edu_flat])

        tail_full = " ".join(
            b.tailored
            for exp in tailored_resume.experience for b in exp.bullets
        ) + " " + " ".join(
            b.tailored
            for prj in tailored_resume.projects for b in prj.bullets
        )

        found_keywords, added_keywords, missing_keywords = [], [], []
        for kw in target_keywords:
            in_orig = keyword_in_text(kw, orig_full)
            in_tail = keyword_in_text(kw, tail_full)
            if in_orig:
                found_keywords.append(kw)
            elif in_tail:
                added_keywords.append(kw)
            else:
                missing_keywords.append(kw)

        tailored_resume.metadata = ATSReport(
            target_keywords=target_keywords,
            found_keywords=found_keywords,
            added_keywords=added_keywords,
            missing_keywords=missing_keywords,
            total_score=round(((len(found_keywords) + len(added_keywords)) / len(target_keywords)) * 100, 2) if target_keywords else 0.0
        )

        yield {"log": "Running Hallucination Guard checks on all AI bullets..."}
        checked_count = reverted_count = 0

        for exp in tailored_resume.experience:
            exp.bullets = exp.bullets[:4]
            for b in exp.bullets:
                b.tailored = b.tailored.replace("**", "")
                checked_count += 1
                if not HallucinationGuard.verify(b.original, b.tailored, target_keywords=target_keywords):
                    yield {"log": f"[GUARD] Blocked hallucinated bullet: {b.tailored[:50]}..."}
                    b.rationale = "⚠️ REJECTED: " + b.rationale + " (Failed hallucination check)"
                    b.tailored = b.original
                    reverted_count += 1

        for prj in tailored_resume.projects:
            prj.bullets = prj.bullets[:3]
            for b in prj.bullets:
                b.tailored = b.tailored.replace("**", "")
                checked_count += 1
                if not HallucinationGuard.verify(b.original, b.tailored, target_keywords=target_keywords):
                    yield {"log": f"[GUARD] Blocked hallucinated bullet: {b.tailored[:50]}..."}
                    b.rationale = "⚠️ REJECTED: " + b.rationale + " (Failed hallucination check)"
                    b.tailored = b.original
                    reverted_count += 1

        yield {"log": f"Guard complete. Checked {checked_count} bullets, reverted {reverted_count}."}
        yield {"result": tailored_resume}
