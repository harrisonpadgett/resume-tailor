import re
from typing import List
from loguru import logger

_HUMBLE_VERBS = {
    "supported", "contributed", "assisted", "helped", "worked",
    "part of", "collaborated", "participated", "involved with",
}
_LEADER_VERBS = {
    "spearheaded", "led", "managed", "directed", "architected",
    "pioneered", "orchestrated", "supervised",
}
_GENERIC_TECH = {"co-worker", "e-commerce", "end-to-end", "cross-functional"}


def _get_tech_terms(text: str) -> set:
    terms = set()
    terms.update(re.findall(r'\b[A-Z]{2,}\b', text))                              # ALL-CAPS acronyms
    terms.update(re.findall(r'\b[a-z]+[A-Z][a-zA-Z]*\b', text))                  # camelCase
    terms.update(re.findall(r'\b[A-Za-z0-9]+(?:\+|-|#|\.)[A-Za-z0-9+#.]*\b', text))  # C++, Node.js, etc.
    return terms


class HallucinationGuard:
    @staticmethod
    def verify(original: str, tailored: str, target_keywords: List[str] = None) -> bool:
        if target_keywords is None:
            target_keywords = []

        orig_nums = set(re.findall(r'\b\d+[%$kM+]*\b', original))
        tail_nums = set(re.findall(r'\b\d+[%$kM+]*\b', tailored))
        if not tail_nums.issubset(orig_nums):
            logger.warning(f"Metric drift! AI added new metrics: {tail_nums - orig_nums}")
            return False

        orig_lower, tail_lower = original.lower(), tailored.lower()
        if (any(v in orig_lower for v in _HUMBLE_VERBS)
                and any(v in tail_lower for v in _LEADER_VERBS)
                and not any(v in orig_lower for v in _LEADER_VERBS)):
            logger.warning(f"Leadership inflation detected: Reverting '{tail_lower[:40]}...'")
            return False

        orig_tech = {n.lower() for n in _get_tech_terms(original)}
        tail_tech = {n.lower() for n in _get_tech_terms(tailored)}
        allowed_tech = {word for kw in target_keywords for word in kw.lower().split()}

        illicit = (tail_tech - orig_tech - allowed_tech) - _GENERIC_TECH
        if illicit:
            logger.warning(f"Potential tech hallucination: {illicit}")
            return False

        return True
