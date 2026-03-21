from pydantic import BaseModel, Field
from typing import List, Optional

class BulletPoint(BaseModel):
    original: str
    tailored: str
    rationale: str

class ExperienceEntry(BaseModel):
    company: str
    role: str
    dates: str
    location: str
    bullets: List[BulletPoint]

class ProjectEntry(BaseModel):
    name: str
    role: str
    bullets: List[BulletPoint]

class ATSReport(BaseModel):
    target_keywords: List[str]
    found_keywords: List[str]
    missing_keywords: List[str]
    total_score: float
    source_hash: Optional[str] = None

class TailoredResumeJSON(BaseModel):
    metadata: Optional[ATSReport] = None
    experience: List[ExperienceEntry]
    projects: List[ProjectEntry]
