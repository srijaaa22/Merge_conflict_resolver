from pydantic import BaseModel
from enum import Enum

class Hunk(BaseModel):
    ours: str
    theirs: str
    branch_name: str
    context_before: list[str]
    context_after: list[str]
    line_number: int
    hunk_id: str

class ConflictedFile(BaseModel):
    filepath: str
    conflict_count: int
    hunks: list[Hunk]

class AnalyzeResponse(BaseModel):
    repo_path: str
    conflicted_files: list[ConflictedFile]
    total_conflicts: int

class AnalyzeRequest(BaseModel):
    repo_path: str

class Strategy(str, Enum):
    OURS = "ours"
    THEIRS = "theirs"
    SMART = "smart"

class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class RiskFlag(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ResolutionStrategy(str, Enum):
    TOOK_OURS = "took_ours"
    TOOK_THEIRS = "took_theirs"
    MERGED_BOTH = "merged_both"
    REWROTE = "rewrote"

class ResolveRequest(BaseModel):
    hunk_id: str
    strategy: Strategy = "smart"
    repo_path: str | None = None

class ResolveResponse(BaseModel):
    resolution: str
    reasoning: str
    confidence: Confidence
    risk_flag: RiskFlag
    strategy: ResolutionStrategy
