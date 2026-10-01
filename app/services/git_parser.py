import logging
import os
import re
import subprocess
from collections import deque

from app.state import analyzed_hunks

logger = logging.getLogger(__name__)

# Lines of surrounding code kept on each side of a conflict (tune here).
CONTEXT_LINES = 10

# Same heuristic git uses: a NUL byte in the first 8000 bytes means "binary".
BINARY_SNIFF_BYTES = 8000

START_MARKER = "<<<<<<<"
SEPARATOR = "======="
END_MARKER = ">>>>>>>"


class InvalidRepoError(Exception):
    """Bad input: path missing or not a git repo (maps to HTTP 400)."""


class GitCommandError(Exception):
    """git itself failed or isn't available (maps to HTTP 500)."""


class UnreadableFileError(Exception):
    """A single file can't be parsed as text (e.g. binary). The file is
    skipped with a warning; it never fails the whole analysis."""


def get_conflicted_files(repo_path: str) -> list[str]:
    if not os.path.exists(repo_path):
        raise InvalidRepoError(f"Path does not exist: {repo_path}")
    if not os.path.exists(os.path.join(repo_path, ".git")):
        raise InvalidRepoError(f"Not a git repository: {repo_path}")

    try:
        # -z: NUL-separated, unquoted paths (safe for spaces / non-ASCII names)
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U", "-z"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise GitCommandError("git executable not found on this machine")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        first_line = next((ln for ln in stderr.splitlines() if ln.strip()), "git command failed")
        if "not a git repository" in stderr.lower():
            raise InvalidRepoError(f"Not a git repository: {repo_path}")
        raise GitCommandError(first_line)

    return [p for p in result.stdout.split("\0") if p]


def _is_start(text: str) -> bool:
    return text == START_MARKER or text.startswith(START_MARKER + " ")


def _is_end(text: str) -> bool:
    return text == END_MARKER or text.startswith(END_MARKER + " ")


def _is_separator(text: str) -> bool:
    return text == SEPARATOR


def _read_lines(file_path: str) -> tuple[list[str], list[str]]:
    """Read a file as text lines (each keeping its trailing "\\n").

    Returns (lines, warnings). Raises UnreadableFileError for binary files.
    Line endings are normalized to "\\n".
    """
    with open(file_path, "rb") as f:
        raw = f.read()

    if b"\x00" in raw[:BINARY_SNIFF_BYTES]:
        raise UnreadableFileError(
            "Binary file skipped: binary conflicts can't be shown as text hunks. "
            "Resolve it with git directly (e.g. 'git checkout --ours' / '--theirs')."
        )

    warnings: list[str] = []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8-sig", errors="replace")
        warnings.append("File is not valid UTF-8; undecodable bytes were replaced in the output.")

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Split on "\n" only (str.splitlines also splits on form feeds etc.)
    lines = re.findall(r"[^\n]*\n|[^\n]+", text)
    return lines, warnings


def parse_conflicts(file_path: str) -> tuple[list[dict], list[str]]:
    """Parse conflict hunks out of one file.

    Returns (hunks, warnings). Never raises on malformed markers: broken or
    unfinished conflicts are dropped and reported in warnings instead.
    Raises UnreadableFileError (binary) or OSError (missing/unreadable file);
    the caller decides how to report those.
    """
    lines, warnings = _read_lines(file_path)

    hunks: list[dict] = []
    state = "normal"  # "normal" | "in_ours" | "in_theirs"
    ours: list[str] = []
    theirs: list[str] = []
    tracking: deque[str] = deque(maxlen=CONTEXT_LINES)
    post_context = 0
    start_line = None

    for line_number, line in enumerate(lines, start=1):
        text = line.rstrip("\n")

        if _is_start(text):
            if state != "normal":
                warnings.append(
                    f"Discarded unfinished conflict starting at line {start_line}: "
                    f"another '{START_MARKER}' appeared at line {line_number} before it was closed."
                )
            state = "in_ours"
            start_line = line_number
            ours = []
            theirs = []
            post_context = 0
            continue

        if state == "in_ours" and _is_separator(text):
            state = "in_theirs"
            continue

        if _is_end(text):
            if state == "in_theirs":
                hunks.append({
                    "ours": "".join(ours),
                    "theirs": "".join(theirs),
                    "branch_name": text[len(END_MARKER):].strip(),
                    "context_before": list(tracking),
                    "context_after": [],
                    "line_number": start_line,
                })
                ours = []
                theirs = []
                tracking.clear()
                post_context = CONTEXT_LINES
                state = "normal"
                continue
            if state == "in_ours":
                warnings.append(
                    f"Discarded malformed conflict starting at line {start_line}: "
                    f"'{END_MARKER}' at line {line_number} appeared with no '{SEPARATOR}' separator."
                )
                ours = []
                theirs = []
                state = "normal"
                continue
            # state == "normal": stray end marker, treat as plain text below

        if state == "in_ours":
            ours.append(line)
        elif state == "in_theirs":
            theirs.append(line)
        else:
            tracking.append(line)
            if post_context > 0 and hunks:
                hunks[-1]["context_after"].append(line)
                post_context -= 1

    if state != "normal":
        missing = "'=======' and '>>>>>>>'" if state == "in_ours" else "'>>>>>>>'"
        warnings.append(
            f"Discarded incomplete conflict starting at line {start_line}: "
            f"end of file reached without {missing}."
        )

    return hunks, warnings


def analyze_repo(repo_path: str) -> dict:
    files_with_conflicts = get_conflicted_files(repo_path)
    conflicted_files = []

    for filepath in files_with_conflicts:
        full_path = os.path.join(repo_path, filepath)

        try:
            hunks, warnings = parse_conflicts(full_path)
        except UnreadableFileError as e:
            hunks, warnings = [], [str(e)]
        except FileNotFoundError:
            hunks, warnings = [], [
                "File not found on disk (possibly deleted on one side of the merge); skipped."
            ]
        except OSError as e:
            hunks, warnings = [], [f"Could not read file ({e.strerror or type(e).__name__}); skipped."]
        except Exception:
            logger.exception("Unexpected error parsing %s", filepath)
            hunks, warnings = [], ["Unexpected error while parsing this file; skipped."]

        if not hunks and not warnings:
            warnings = [
                "Git lists this file as conflicted, but no conflict markers were found. "
                "It may already be resolved but not yet staged with 'git add'."
            ]

        for index, hunk in enumerate(hunks):
            hunk["hunk_id"] = f"{filepath}::{index}"
            hunk["filepath"] = filepath
            analyzed_hunks[hunk["hunk_id"]] = hunk

        conflicted_files.append({
            "filepath": filepath,
            "conflict_count": len(hunks),
            "hunks": hunks,
            "warnings": warnings,
        })

    total = sum(f["conflict_count"] for f in conflicted_files)

    message = None
    if not conflicted_files:
        message = "No merge conflicts found."
    elif total == 0:
        message = (
            "Git reports conflicted files, but no parsable conflict hunks were found. "
            "See each file's 'warnings'."
        )

    return {
        "repo_path": repo_path,
        "conflicted_files": conflicted_files,
        "total_conflicts": total,
        "message": message,
    }