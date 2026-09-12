import subprocess
import os

def get_conflicted_files(repo_path: str) -> list[str]:
    if not os.path.exists(repo_path):
        raise Exception(f"Path does not exist: {repo_path}")
    if not os.path.exists(os.path.join(repo_path, ".git")):
        raise Exception(f"Not a git repository: {repo_path}")
    try:
        result = subprocess.run(["git", "diff", "--name-only", "--diff-filter=U"], cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(result.stderr)
        return result.stdout.strip().split("\n")
    except Exception as e:
        raise e

def parse_conflicts(file_path: str) -> list[dict]:
    with open(file_path, "r") as f:
        content = f.readlines()

    state = "normal"
    conflicted_blocks = []
    ours = []
    theirs = []
    tracking = []
    post_context = 0
    line_number = 0
    conflict_start_line = None

    for i, line in enumerate(content):
        line_number = i + 1

        if state == "normal" and not line.startswith(("<<<<<<<", "=======", ">>>>>>>")):
            tracking.append(line)
            if post_context > 0:
                conflicted_blocks[-1]["context_after"].append(line)
                post_context -= 1

        if "<<<<<<<" in line:
            state = "in_ours"
            conflict_start_line = line_number
            continue

        if "=======" in line:
            state = "in_theirs"
            continue

        if ">>>>>>>" in line:
            branch_name = line.replace(">>>>>>>", "").strip()
            state = "normal"
            conflicted_blocks.append({
                "ours": "".join(ours),
                "theirs": "".join(theirs),
                "branch_name": branch_name,
                "context_before": tracking[-3:],
                "context_after": [],
                "line_number": conflict_start_line
            })
            ours = []
            theirs = []
            tracking = []
            post_context = 3
            continue

        if state == "in_ours":
            ours.append(line)
        elif state == "in_theirs":
            theirs.append(line)

    return conflicted_blocks

def analyze_repo(repo_path: str) -> dict:
    files_with_conflicts = get_conflicted_files(repo_path)
    conflicted_files = []

    for filepath in files_with_conflicts:
        full_path = os.path.join(repo_path, filepath)
        hunks = parse_conflicts(full_path)

        for index, hunk in enumerate(hunks):
            hunk["hunk_id"] = f"{filepath}::{index}"

        conflicted_files.append({
            "filepath": filepath,
            "conflict_count": len(hunks),
            "hunks": hunks
        })

    return {
        "repo_path": repo_path,
        "conflicted_files": conflicted_files,
        "total_conflicts": sum(f["conflict_count"] for f in conflicted_files)
    }
