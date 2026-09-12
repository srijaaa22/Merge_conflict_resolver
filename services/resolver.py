import subprocess

def get_conflicted_files(repo_path: str) -> list[str]:
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

    for i in content:
        if state == "normal" and not i.startswith(("<<<<<<<", "=======", ">>>>>>>")):
            tracking.append(i)
            if post_context > 0:
                conflicted_blocks[-1]["context"].append(i)
                post_context -= 1

        if "<<<<<<<" in i:
            state = "in_ours"
            continue

        if "=======" in i:
            state = "in_theirs"
            continue

        if ">>>>>>>" in i:
            state = "normal"
            conflicted_blocks.append({"ours": ours, "theirs": theirs, "context": tracking[-3:]})
            ours = []
            theirs = []
            tracking = []
            post_context = 3
            continue

        if state == "in_ours":
            ours.append(i)
        elif state == "in_theirs":
            theirs.append(i)

    return conflicted_blocks