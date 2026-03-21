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

        def get_proper_nouns(text):
            return set(re.findall(r'\b[A-Z0-9][a-zA-Z0-9+#.]*\b', text))
        
        orig_nouns = {n.lower() for n in get_proper_nouns(original)}
        tail_nouns = {n.lower() for n in get_proper_nouns(tailored)}
        
        allowed_nouns = {"the", "a", "an", "i", "to", "with", "in", "as", "our", "its", "by", "from", "on", "into", "within", "for", "and", "or"}
        for k in target_keywords:
            for word in k.lower().split():
                allowed_nouns.add(word)
        
        illicit_additions = tail_nouns - orig_nouns - allowed_nouns
        if illicit_additions:
            generic_nouns = {"marketplace", "solutions", "environment", "platform", "applications"}
            if illicit_additions - generic_nouns:
                logger.warning(f"Potential tech/noun hallucination: {illicit_additions}")
                return False
            
        return True
