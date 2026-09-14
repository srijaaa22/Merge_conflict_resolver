from pydantic import BaseModel

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