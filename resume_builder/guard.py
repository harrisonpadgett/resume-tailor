import re
from typing import List
from loguru import logger

class HallucinationGuard:
    @staticmethod
    def verify(original: str, tailored: str, target_keywords: List[str] = None) -> bool:
        if target_keywords is None: target_keywords = []
        
        orig_nums = set(re.findall(r'\b\d+[%$kM+]*\b', original))
        tail_nums = set(re.findall(r'\b\d+[%$kM+]*\b', tailored))
        if not tail_nums.issubset(orig_nums):
            added = tail_nums - orig_nums
            logger.warning(f"Metric drift! AI added new metrics: {added}")
            return False
            
        humble_verbs = {"supported", "contributed", "assisted", "helped", "worked", "part of", "collaborated", "participated", "involved with"}
        leader_verbs = {"spearheaded", "led", "managed", "directed", "architected", "pioneered", "orchestrated", "supervised"}
        orig_lower = original.lower()
        tail_lower = tailored.lower()
        has_humble = any(v in orig_lower for v in humble_verbs)
        has_leader = any(v in tail_lower for v in leader_verbs)
        if has_humble and has_leader and not any(v in orig_lower for v in leader_verbs):
            logger.warning(f"Leadership inflation detected: Reverting '{tail_lower[:40]}...'")
            return False

        def get_tech_terms(text):
            # Only capture strict technology signatures to avoid false positives on normal words:
            # 1. ALL CAPS acronyms (e.g., AWS, API, SQL)
            # 2. camelCase words (e.g., JavaScript, GitHub)
            # 3. Terms with specific tech symbols (e.g., C++, C#, Node.js, .NET)
            terms = set()
            terms.update(re.findall(r'\b[A-Z]{2,}\b', text)) # ALL CAPS
            terms.update(re.findall(r'\b[a-z]+[A-Z][a-zA-Z]*\b', text)) # camelCase
            terms.update(re.findall(r'\b[A-Za-z0-9]+(?:\+|-|#|\.)[A-Za-z0-9+#.]*\b', text)) # Symbols
            return terms
        
        orig_tech = {n.lower() for n in get_tech_terms(original)}
        tail_tech = {n.lower() for n in get_tech_terms(tailored)}
        
        allowed_tech = set()
        for k in target_keywords:
            for word in k.lower().split():
                allowed_tech.add(word)
        
        illicit_tech = tail_tech - orig_tech - allowed_tech
        if illicit_tech:
            # Ignore some common non-tech false positives
            generic_ignore = {"co-worker", "e-commerce", "end-to-end", "cross-functional"}
            illicit_tech = illicit_tech - generic_ignore
            if illicit_tech:
                logger.warning(f"Potential tech hallucination: {illicit_tech}")
                return False
            
        return True
