"""L1 document review: deterministic checks and fixes for plan/checklist consistency.

Usage:
    python3 review_plan.py --context PATH --target NAME --files-json PATH --check [--json] [--agent-md PATH]
    python3 review_plan.py --context PATH --target NAME --files-json PATH --fix [--agent-md PATH]
"""
import re
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------
SEV_ERROR = "error"
SEV_WARNING = "warning"
SEV_ADVISORY = "advisory"

# ---------------------------------------------------------------------------
# Check ID constants — C-series (Consistency)
# ---------------------------------------------------------------------------
C_001 = "C-001"
C_002 = "C-002"
C_003 = "C-003"
C_004 = "C-004"
C_005 = "C-005"
C_006 = "C-006"
C_007 = "C-007"
C_008 = "C-008"

# ---------------------------------------------------------------------------
# Check ID constants — M-series (Completeness)
# ---------------------------------------------------------------------------
M_001 = "M-001"
M_002 = "M-002"
M_003 = "M-003"

# ---------------------------------------------------------------------------
# Check ID constants — B-series (Best Practice)
# ---------------------------------------------------------------------------
B_001 = "B-001"
B_002 = "B-002"
B_003 = "B-003"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class Violation:
    """A single review finding."""
    id: str
    category: str
    severity: str
    message: str
    auto_fixable: bool = False
    file: Optional[str] = None
    plan_ref: Optional[str] = None
    checklist_ref: Optional[str] = None


@dataclass
class Fix:
    """A single applied fix."""
    id: str
    action: str
    file: str
    description: str
    diff_preview: str = ""


# ---------------------------------------------------------------------------
# Regex patterns for plan phase headings
# ---------------------------------------------------------------------------
# Parallel: ### W0: Title  or  ### W1.Auth: Title
_RE_PARALLEL_PHASE = re.compile(
    r"^###\s+(W\d+(?:\.\w+)?)\s*:\s*(.+)$"
)
# Sequential: ### Phase 1: Title  or  ### 3.1 Phase 1: Title
_RE_SEQUENTIAL_PHASE = re.compile(
    r"^###\s+(?:\d+\.\d+\s+)?Phase\s+(\d+)\s*:\s*(.+)$"
)
# HTML comment metadata
_RE_AGENT = re.compile(r"^<!--\s*agent\s*:\s*(.+?)\s*-->$")
_RE_FILES = re.compile(r"^<!--\s*files\s*:\s*(.+?)\s*-->$")
_RE_DEPENDS = re.compile(r"^<!--\s*depends-on\s*:\s*(.+?)\s*-->$")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_plan_phases(path: str) -> List[dict]:
    """Parse plan document phase headings and their HTML comment metadata.

    Returns list of dicts:
        [{id, title, level, agent, depends_on, files_globs}]
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    phases: List[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        phase = None

        # Try parallel format first
        m = _RE_PARALLEL_PHASE.match(line)
        if m:
            phase = {
                "id": m.group(1),
                "title": m.group(2).strip(),
                "level": 3,
                "agent": None,
                "depends_on": [],
                "files_globs": [],
            }
        else:
            # Try sequential format
            m = _RE_SEQUENTIAL_PHASE.match(line)
            if m:
                phase = {
                    "id": m.group(1),
                    "title": m.group(2).strip(),
                    "level": 3,
                    "agent": None,
                    "depends_on": [],
                    "files_globs": [],
                }

        if phase is not None:
            # Scan subsequent lines for HTML comment metadata
            j = i + 1
            while j < len(lines):
                meta_line = lines[j].rstrip("\n")
                if not meta_line.startswith("<!--"):
                    break
                ma = _RE_AGENT.match(meta_line)
                if ma:
                    phase["agent"] = ma.group(1).strip()
                    j += 1
                    continue
                mf = _RE_FILES.match(meta_line)
                if mf:
                    globs = [g.strip() for g in mf.group(1).split(",") if g.strip()]
                    phase["files_globs"] = globs
                    j += 1
                    continue
                md = _RE_DEPENDS.match(meta_line)
                if md:
                    raw = md.group(1).strip()
                    if raw in ("—", "-", ""):
                        phase["depends_on"] = []
                    else:
                        phase["depends_on"] = [
                            d.strip() for d in raw.split(",") if d.strip()
                        ]
                    j += 1
                    continue
                # Unknown comment, skip
                j += 1
            phases.append(phase)
        i += 1

    return phases


# ---------------------------------------------------------------------------
# Additional regex patterns
# ---------------------------------------------------------------------------
# Task-level file declaration: **文件**: `path.go`, `path2.go`
_RE_TASK_FILE = re.compile(r"\*\*文件\*\*\s*:\s*(.+)")
# Backtick-wrapped path
_RE_BACKTICK_PATH = re.compile(r"`([^`]+)`")
# Task heading: #### W1.Auth.1 Title  or  #### 1.1 Title
_RE_PARALLEL_TASK = re.compile(r"^####\s+(W\d+(?:\.\w+)*\.\d+)\s+(.+)$")
_RE_SEQUENTIAL_TASK = re.compile(r"^####\s+(\d+(?:\.\d+)+)\s+(.+)$")
# Checklist section headings
# Parallel: ## W1.Auth: Title [role]
_RE_CL_PARALLEL_SECTION = re.compile(r"^##\s+(W\d+(?:\.\w+)?)\s*:\s*(.+?)(?:\s*\[.+?\])?\s*$")
# Sequential canonical: ## Phase 1: Title
_RE_CL_SEQUENTIAL_SECTION = re.compile(r"^##\s+Phase\s+(\d+)\s*:\s*(.+)$")
# Sequential legacy: ## 1 Phase 1: Title
_RE_CL_SEQUENTIAL_SECTION_LEGACY = re.compile(
    r"^##\s+(\d+)\s+Phase\s+(\d+)\s*:\s*(.+)$"
)
# Sequential legacy: ## 1 Title
_RE_CL_SEQUENTIAL_SECTION_NUMERIC = re.compile(r"^##\s+(\d+)\s+(.+)$")
# Checklist item with machine-readable ID:
# - [ ] 1.1 Text
# - [x] W1.Auth.1 Text
_RE_CL_TASK_ITEM = re.compile(
    r"^-\s+\[([ xX])\]\s+((?:W\d+(?:\.\w+)*\.\d+)|(?:\d+(?:\.\d+)+))\s+(.*)"
)
# Any checkbox line, including legacy subsection detail bullets without IDs.
_RE_CL_ANY_ITEM = re.compile(r"^-\s+\[([ xX])\]\s+(.*)")
# Checklist subsection heading with numeric prefix
_RE_CL_SUBSECTION = re.compile(r"^###\s+(\d+(?:\.\d+)+)\s+(.+)$")
# Spec ## heading
_RE_SPEC_SECTION = re.compile(r"^##\s+(.+)$")
# phase-mapping HTML comment
_RE_PHASE_MAPPING = re.compile(r"^<!--\s*phase-mapping\s*:\s*(.+?)\s*-->$")
# Change summary table row: | file | change-type | Phase |
_RE_CHANGE_TABLE_ROW = re.compile(r"^\|\s*`?([^|`]+?)`?\s*\|")


def _match_checklist_section_heading(line: str) -> Optional[dict]:
    """Parse a checklist section heading across canonical and legacy formats."""
    m = _RE_CL_PARALLEL_SECTION.match(line)
    if m:
        return {"id": m.group(1), "title": m.group(2).strip(), "style": "parallel"}

    m = _RE_CL_SEQUENTIAL_SECTION.match(line)
    if m:
        return {"id": m.group(1), "title": m.group(2).strip(), "style": "sequential"}

    m = _RE_CL_SEQUENTIAL_SECTION_LEGACY.match(line)
    if m:
        return {"id": m.group(2), "title": m.group(3).strip(), "style": "sequential_legacy"}

    m = _RE_CL_SEQUENTIAL_SECTION_NUMERIC.match(line)
    if m:
        return {"id": m.group(1), "title": m.group(2).strip(), "style": "sequential_numeric"}

    return None


def _canonicalize_sequential_task_id(raw_id: str, current_phase_id: Optional[str]) -> str:
    """Normalize legacy sequential task IDs like 4.2.1 to phase-local 2.1."""
    if not current_phase_id:
        return raw_id

    parts = raw_id.split(".")
    if len(parts) == 3 and parts[-2] == str(current_phase_id):
        return f"{current_phase_id}.{parts[-1]}"

    return raw_id


def parse_plan_file_declarations(path: str) -> List[dict]:
    """Extract file path declarations from plan document.

    Returns list of dicts:
        [{phase_id, glob?, exact_path?, source}]
    where source is one of: phase_metadata, task_declaration, change_summary_table
    """
    phases = parse_plan_phases(path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    decls: List[dict] = []
    current_phase_id = None
    current_task_id = None
    in_change_table = False

    for line_raw in lines:
        line = line_raw.rstrip("\n")

        # Track current phase
        m = _RE_PARALLEL_PHASE.match(line)
        if m:
            current_phase_id = m.group(1)
            current_task_id = None
            in_change_table = False
            continue
        m = _RE_SEQUENTIAL_PHASE.match(line)
        if m:
            current_phase_id = m.group(1)
            current_task_id = None
            in_change_table = False
            continue

        mtask = _RE_PARALLEL_TASK.match(line)
        if mtask:
            current_task_id = mtask.group(1)
            continue
        mtask = _RE_SEQUENTIAL_TASK.match(line)
        if mtask:
            current_task_id = _canonicalize_sequential_task_id(mtask.group(1), current_phase_id)
            continue

        # Phase-level <!-- files: --> metadata
        mf = _RE_FILES.match(line)
        if mf and current_phase_id:
            for g in mf.group(1).split(","):
                g = g.strip()
                if g:
                    decls.append({
                        "phase_id": current_phase_id,
                        "task_id": None,
                        "glob": g,
                        "exact_path": None,
                        "source": "phase_metadata",
                    })
            continue

        # Task-level **文件**: declaration
        mt = _RE_TASK_FILE.match(line.strip())
        if mt and current_phase_id:
            paths_str = mt.group(1)
            for pm in _RE_BACKTICK_PATH.finditer(paths_str):
                decls.append({
                    "phase_id": current_phase_id,
                    "task_id": current_task_id,
                    "glob": None,
                    "exact_path": pm.group(1),
                    "source": "task_declaration",
                })
            continue

        # Change summary table detection
        if "| 文件 |" in line and "| 变更类型 |" in line:
            in_change_table = True
            continue
        if in_change_table:
            if line.startswith("|") and not line.startswith("|--"):
                mr = _RE_CHANGE_TABLE_ROW.match(line)
                if mr:
                    fpath = mr.group(1).strip()
                    if fpath and fpath != "文件":
                        decls.append({
                            "phase_id": current_phase_id,
                            "task_id": None,
                            "glob": None,
                            "exact_path": fpath,
                            "source": "change_summary_table",
                        })
            elif not line.startswith("|"):
                in_change_table = False

    return decls


def parse_checklist_sections(path: str) -> List[dict]:
    """Parse checklist section headings and their items.

    Returns list of dicts:
        [{id, title, items: [{id, text, checked}]}]
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections: List[dict] = []
    current_section = None

    for line_raw in lines:
        line = line_raw.rstrip("\n")

        section = _match_checklist_section_heading(line)
        if section:
            current_section = {
                "id": section["id"],
                "title": section["title"],
                "items": [],
            }
            sections.append(current_section)
            continue

        # Check for items
        mi = _RE_CL_TASK_ITEM.match(line)
        if mi and current_section is not None:
            current_section["items"].append({
                "id": mi.group(2),
                "text": mi.group(3).strip(),
                "checked": mi.group(1).lower() == "x",
            })

    return sections


def parse_checklist_items(path: str) -> List[dict]:
    """Parse checklist into flat item list with section_id.

    Returns list of dicts:
        [{id, text, checked, section_id}]
    """
    sections = parse_checklist_sections(path)
    items: List[dict] = []
    for section in sections:
        for item in section["items"]:
            items.append({
                "id": item["id"],
                "text": item["text"],
                "checked": item["checked"],
                "section_id": section["id"],
            })
    return items


def parse_checklist_section_entries(path: str) -> List[dict]:
    """Parse checklist sections into task-like entries for continuity/count checks.

    Entry sources:
      - canonical/legacy task items with machine-readable IDs
      - legacy subsection headings like `### 2.1 ...`
      - top-level checkbox items without IDs (count only; ignored for ID checks)
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections: List[dict] = []
    current_section = None
    current_section_id = None
    current_subsection_id = None

    for line_raw in lines:
        line = line_raw.rstrip("\n")

        section = _match_checklist_section_heading(line)
        if section:
            current_section = {
                "id": section["id"],
                "title": section["title"],
                "entries": [],
            }
            sections.append(current_section)
            current_section_id = section["id"]
            current_subsection_id = None
            continue

        m = _RE_CL_SUBSECTION.match(line)
        if m and current_section is not None:
            task_id = m.group(1)
            if str(current_section_id).isdigit():
                task_id = _canonicalize_sequential_task_id(task_id, current_section_id)
            current_section["entries"].append({
                "id": task_id,
                "text": m.group(2).strip(),
                "checked": None,
                "source": "subsection",
            })
            current_subsection_id = task_id
            continue

        mi = _RE_CL_TASK_ITEM.match(line)
        if mi and current_section is not None:
            task_id = mi.group(2)
            if str(current_section_id).isdigit():
                task_id = _canonicalize_sequential_task_id(task_id, current_section_id)
            current_section["entries"].append({
                "id": task_id,
                "text": mi.group(3).strip(),
                "checked": mi.group(1).lower() == "x",
                "source": "item",
            })
            continue

        ma = _RE_CL_ANY_ITEM.match(line)
        if ma and current_section is not None and current_subsection_id is None:
            current_section["entries"].append({
                "id": None,
                "text": ma.group(2).strip(),
                "checked": ma.group(1).lower() == "x",
                "source": "top_level_item",
            })

    return sections


def parse_checklist_task_refs(path: str) -> List[dict]:
    """Parse checklist task refs from explicit item IDs and subsection headings."""
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    refs: List[dict] = []
    seen_ids = set()
    current_section_id = None

    for line_raw in lines:
        line = line_raw.rstrip("\n")

        section = _match_checklist_section_heading(line)
        if section:
            current_section_id = section["id"]
            continue

        m = _RE_CL_SUBSECTION.match(line)
        if m and current_section_id is not None:
            task_id = m.group(1)
            if str(current_section_id).isdigit():
                task_id = _canonicalize_sequential_task_id(task_id, current_section_id)
            if task_id not in seen_ids:
                refs.append({
                    "id": task_id,
                    "text": m.group(2).strip(),
                    "checked": None,
                    "section_id": current_section_id,
                    "source": "subsection",
                })
                seen_ids.add(task_id)
            continue

        mi = _RE_CL_TASK_ITEM.match(line)
        if mi and current_section_id is not None:
            task_id = mi.group(2)
            if str(current_section_id).isdigit():
                task_id = _canonicalize_sequential_task_id(task_id, current_section_id)
            if task_id not in seen_ids:
                refs.append({
                    "id": task_id,
                    "text": mi.group(3).strip(),
                    "checked": mi.group(1).lower() == "x",
                    "section_id": current_section_id,
                    "source": "item",
                })
                seen_ids.add(task_id)

    return refs


def parse_spec_sections(path: str) -> List[dict]:
    """Extract spec ## section headings and line ranges.

    Returns list of dicts:
        [{level, title, line_start, line_end}]
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    sections: List[dict] = []
    for i, line_raw in enumerate(lines):
        line = line_raw.rstrip("\n")
        m = _RE_SPEC_SECTION.match(line)
        if m:
            # Close previous section
            if sections:
                sections[-1]["line_end"] = i  # exclusive
            sections.append({
                "level": 2,
                "title": m.group(1).strip(),
                "line_start": i + 1,  # 1-based
                "line_end": len(lines),  # default to end
            })

    # Adjust last section end
    if sections:
        sections[-1]["line_end"] = len(lines)

    return sections


def parse_dag_metadata(path: str) -> dict:
    """Extract DAG structure from parallel plan phase headings.

    Returns dict:
        {phases: [id], edges: [(from, to)]}
    """
    phases_list = parse_plan_phases(path)
    phase_ids = [p["id"] for p in phases_list]
    edges = []
    for p in phases_list:
        for dep in p["depends_on"]:
            edges.append((dep, p["id"]))

    return {"phases": phase_ids, "edges": edges}


def parse_test_checklist_mappings(path: str) -> dict:
    """Extract implementation phase mappings from test checklist.

    Returns dict:
        {impl_phase_id: [test_section_id]}
    """
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    mappings: dict = {}
    current_section_id = None
    current_section_has_explicit_mapping = False

    def _flush_implicit_mapping():
        if current_section_id is None or current_section_has_explicit_mapping:
            return
        mappings.setdefault(current_section_id, []).append(current_section_id)

    for line_raw in lines:
        line = line_raw.rstrip("\n")

        section = _match_checklist_section_heading(line)
        if section:
            _flush_implicit_mapping()
            current_section_id = section["id"]
            current_section_has_explicit_mapping = False
            continue

        mp = _RE_PHASE_MAPPING.match(line)
        if mp and current_section_id is not None:
            impl_id = mp.group(1).strip()
            mappings.setdefault(impl_id, []).append(current_section_id)
            current_section_has_explicit_mapping = True

    _flush_implicit_mapping()

    return mappings


# ---------------------------------------------------------------------------
# Header parsing helper
# ---------------------------------------------------------------------------
_RE_HEADER_FIELD = re.compile(r"^>\s*\*\*(.+?)\*\*\s*:\s*(.+)$")
_RE_SEMANTIC_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_SEMANTIC_ERROR_KEYWORDS = (
    "error",
    "invalid",
    "fail",
    "failure",
    "timeout",
    "forbidden",
    "unauthorized",
    "not found",
    "conflict",
    "boundary",
    "edge case",
    "validation",
    "rollback",
    "fallback",
    "错误",
    "失败",
    "异常",
    "超时",
    "越界",
    "边界",
    "校验",
    "验证",
    "权限",
    "拒绝",
    "不存在",
    "冲突",
    "回滚",
    "降级",
)


def _parse_header(path: str) -> dict:
    """Extract blockquote header fields from a markdown file.

    Returns dict of field_name → value, e.g. {"版本": "1.0", "状态": "active", ...}
    """
    result = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _RE_HEADER_FIELD.match(line)
            if m:
                result[m.group(1).strip()] = m.group(2).strip()
            elif result and not line.startswith(">"):
                break  # past the header block
    return result


def _is_parallel_plan(plan_path: str) -> bool:
    """Check if plan uses legacy parallel execution structure."""
    header = _parse_header(plan_path)
    if header.get("执行模式", "").lower() == "parallel":
        return True

    for phase in parse_plan_phases(plan_path):
        if str(phase["id"]).startswith("W"):
            return True

    return False


def _parse_plan_task_ids(path: str) -> List[str]:
    """Extract task heading IDs (#### level) from plan."""
    ids = []
    for task in _parse_plan_tasks(path):
        ids.append(task["id"])
    return ids


def _parse_plan_tasks(path: str) -> List[dict]:
    """Extract task heading IDs and titles from plan."""
    tasks = []
    current_phase_id = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            m = _RE_PARALLEL_PHASE.match(line)
            if m:
                current_phase_id = m.group(1)
                continue
            m = _RE_SEQUENTIAL_PHASE.match(line)
            if m:
                current_phase_id = m.group(1)
                continue
            m = _RE_PARALLEL_TASK.match(line)
            if m:
                tasks.append({"id": m.group(1), "title": m.group(2).strip()})
                continue
            m = _RE_SEQUENTIAL_TASK.match(line)
            if m:
                tasks.append({
                    "id": _canonicalize_sequential_task_id(m.group(1), current_phase_id),
                    "title": m.group(2).strip(),
                })
    return tasks


def _normalize_semantic_text(text: str) -> str:
    """Normalize natural-language text for rough semantic comparison."""
    lowered = text.lower()
    lowered = re.sub(r"`([^`]+)`", r" \1 ", lowered)
    lowered = re.sub(r"[_/:\-]+", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _semantic_tokens(text: str) -> set:
    """Tokenize English/CJK text into a set for overlap comparison."""
    return set(_RE_SEMANTIC_TOKEN.findall(_normalize_semantic_text(text)))


def _texts_semantically_close(left: str, right: str) -> bool:
    """Heuristic filter for obvious checklist/plan wording drift."""
    left_norm = _normalize_semantic_text(left)
    right_norm = _normalize_semantic_text(right)
    if not left_norm or not right_norm:
        return True
    if left_norm == right_norm or left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = _semantic_tokens(left)
    right_tokens = _semantic_tokens(right)
    if not left_tokens or not right_tokens:
        return True

    overlap = len(left_tokens & right_tokens)
    smaller = min(len(left_tokens), len(right_tokens))
    union = len(left_tokens | right_tokens)
    coverage = overlap / smaller if smaller else 1.0
    jaccard = overlap / union if union else 1.0
    return coverage >= 0.6 or jaccard >= 0.5


def _collect_spec_attention_points(path: str) -> List[dict]:
    """Locate spec sections that discuss error paths, validation, or boundaries."""
    sections = parse_spec_sections(path)
    if not sections:
        return []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    attention_points = []
    for section in sections:
        hits = []
        for idx in range(section["line_start"] - 1, section["line_end"]):
            line = lines[idx].strip()
            if not line or line.startswith("#") or line.startswith("```"):
                continue
            lowered = line.lower()
            if any(keyword in lowered or keyword in line for keyword in _SEMANTIC_ERROR_KEYWORDS):
                hits.append({
                    "line": idx + 1,
                    "text": line,
                })
        if hits:
            attention_points.append({
                "title": section["title"],
                "line_start": section["line_start"],
                "hits": hits[:5],
            })

    return attention_points


def _parse_agent_roles(agent_md_path: str) -> List[str]:
    """Extract agent role IDs from AGENTS.md §6.1 table."""
    roles = []
    if not agent_md_path or not os.path.exists(agent_md_path):
        return roles
    with open(agent_md_path, "r", encoding="utf-8") as f:
        in_table = False
        for line in f:
            line = line.rstrip("\n")
            if "| 角色 ID |" in line or "| 角色ID |" in line:
                in_table = True
                continue
            if in_table and line.startswith("|"):
                if line.startswith("|--") or line.startswith("| --"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                # parts[0] is empty (before first |), parts[1] is role ID
                if len(parts) >= 3 and parts[1]:
                    role_id = parts[1].strip("`").strip()
                    if role_id:
                        roles.append(role_id)
            elif in_table and not line.startswith("|"):
                break
    return roles


# ---------------------------------------------------------------------------
# Checkers
# ---------------------------------------------------------------------------
import os


def check_consistency(files: dict, agent_md_path: str = None) -> List[Violation]:
    """Run C-001 through C-008 consistency checks.

    Args:
        files: dict of {role: path} for plan, checklist, etc.
        agent_md_path: optional path to AGENTS.md for C-005.

    Returns list of Violation objects.
    """
    plan_path = files.get("plan")
    cl_path = files.get("checklist")
    if not plan_path or not cl_path:
        return []

    violations: List[Violation] = []
    is_parallel = _is_parallel_plan(plan_path)
    plan_phases = parse_plan_phases(plan_path)
    cl_sections = parse_checklist_sections(cl_path)
    plan_task_ids = _parse_plan_task_ids(plan_path)
    cl_task_refs = parse_checklist_task_refs(cl_path)
    plan_header = _parse_header(plan_path)
    cl_header = _parse_header(cl_path)

    plan_phase_ids = {p["id"] for p in plan_phases}
    cl_section_ids = {s["id"] for s in cl_sections}
    cl_task_ids = {i["id"] for i in cl_task_refs}
    plan_task_id_set = set(plan_task_ids)

    # C-001: Plan phase heading ↔ checklist section heading alignment
    for phase in plan_phases:
        if phase["id"] not in cl_section_ids:
            violations.append(Violation(
                id=C_001,
                category="consistency",
                severity=SEV_ERROR,
                message=f'Plan phase "{phase["id"]}: {phase["title"]}" has no matching checklist section',
                auto_fixable=True,
                file=cl_path,
                plan_ref=phase["id"],
            ))

    # C-002: Bidirectional orphan check
    # Forward orphan checklist items are routed to semantic_pending (S-004)
    # so they can be judged as legitimate additions vs drift.
    # Reverse: each plan task should have at least one checklist task reference
    for task_id in plan_task_ids:
        if task_id not in cl_task_ids:
            violations.append(Violation(
                id=C_002,
                category="consistency",
                severity=SEV_ERROR,
                message=f'Plan task "{task_id}" has no matching checklist item',
                file=plan_path,
                plan_ref=task_id,
            ))

    # C-003: Section item numbering continuity
    for section in parse_checklist_section_entries(cl_path):
        entries = section["entries"]
        numbered_entries = [entry for entry in entries if entry["id"]]
        if len(numbered_entries) < 2:
            continue
        # Extract the numeric suffix from each item ID
        prefix = section["id"]
        prev_num = None
        for item in numbered_entries:
            item_id = item["id"]
            # Try to extract the last numeric component
            parts = item_id.split(".")
            try:
                num = int(parts[-1])
            except (ValueError, IndexError):
                continue
            if prev_num is not None and num != prev_num + 1:
                violations.append(Violation(
                    id=C_003,
                    category="consistency",
                    severity=SEV_WARNING,
                    message=f'Numbering gap in section "{prefix}": after {prefix}.{prev_num} expected {prefix}.{prev_num + 1}, found {item_id}',
                    auto_fixable=True,
                    file=cl_path,
                    checklist_ref=item_id,
                ))
            prev_num = num

    # C-004: Header version/date sync
    for field_name, fixable in [("版本", True), ("更新日期", True), ("状态", False)]:
        plan_val = plan_header.get(field_name)
        cl_val = cl_header.get(field_name)
        if plan_val and cl_val and plan_val != cl_val:
            violations.append(Violation(
                id=C_004,
                category="consistency",
                severity=SEV_WARNING,
                message=f'Header {field_name} drift: plan={plan_val}, checklist={cl_val}',
                auto_fixable=fixable,
                file=cl_path,
            ))

    # C-005: Parallel plan agent role validation (parallel only)
    if is_parallel and agent_md_path:
        valid_roles = _parse_agent_roles(agent_md_path)
        if valid_roles:
            for phase in plan_phases:
                if phase["agent"] and phase["agent"] not in valid_roles:
                    violations.append(Violation(
                        id=C_005,
                        category="consistency",
                        severity=SEV_ERROR,
                        message=f'Phase "{phase["id"]}" agent role "{phase["agent"]}" not found in AGENTS.md',
                        file=plan_path,
                        plan_ref=phase["id"],
                    ))

    # C-006: depends-on reference validation (parallel only)
    if is_parallel:
        for phase in plan_phases:
            for dep in phase["depends_on"]:
                if dep not in plan_phase_ids:
                    violations.append(Violation(
                        id=C_006,
                        category="consistency",
                        severity=SEV_ERROR,
                        message=f'Phase "{phase["id"]}" depends on "{dep}" which does not exist',
                        file=plan_path,
                        plan_ref=phase["id"],
                    ))

    # C-007: files metadata existence check (parallel only)
    if is_parallel:
        for phase in plan_phases:
            if not phase["files_globs"]:
                violations.append(Violation(
                    id=C_007,
                    category="consistency",
                    severity=SEV_ERROR,
                    message=f'Phase "{phase["id"]}" has no <!-- files: --> metadata',
                    file=plan_path,
                    plan_ref=phase["id"],
                ))

    # C-008: test-checklist section mapping validation
    tcl_path = files.get("test-checklist")
    if tcl_path and os.path.exists(tcl_path):
        mappings = parse_test_checklist_mappings(tcl_path)
        # Also need to know valid impl phase IDs from checklist
        for impl_id in mappings:
            if impl_id not in plan_phase_ids and impl_id not in cl_section_ids:
                violations.append(Violation(
                    id=C_008,
                    category="consistency",
                    severity=SEV_WARNING,
                    message=f'test-checklist mapping "{impl_id}" does not match any impl phase',
                    file=tcl_path,
                ))

    return violations


def _find_unique_spec_candidate(context_yaml_path: str) -> Optional[str]:
    """Return the unique candidate spec path for the current context target."""
    if not context_yaml_path or not os.path.exists(context_yaml_path):
        return None

    import yaml

    with open(context_yaml_path, "r", encoding="utf-8") as f:
        ctx = yaml.safe_load(f) or {}

    plan_name = ctx.get("metadata", {}).get("name", "")
    if not plan_name:
        return None

    spec_dir = os.path.abspath(
        os.path.join(os.path.dirname(context_yaml_path), "..", "..", "spec")
    )
    if not os.path.isdir(spec_dir):
        return None

    candidates = []
    for fname in os.listdir(spec_dir):
        if fname.endswith(".md") and plan_name in fname:
            candidates.append(os.path.join(spec_dir, fname))

    if len(candidates) != 1:
        return None

    return candidates[0]


def collect_semantic_pending(files: dict) -> List[dict]:
    """Collect semantic-pending review items that need LLM judgment.

    Baseline semantic review is intentionally broader than deterministic
    structure checks:
      - S-001: spec section coverage needs LLM judgment
      - S-002: spec error/boundary handling coverage needs LLM judgment
      - S-003: script-flagged wording drift between plan/checklist items
      - S-004: orphan checklist items may be legitimate additions or drift
    """
    plan_path = files.get("plan")
    cl_path = files.get("checklist")
    if not plan_path or not cl_path:
        return []

    plan_tasks = _parse_plan_tasks(plan_path)
    plan_task_map = {task["id"]: task["title"] for task in plan_tasks}
    plan_task_id_set = set(plan_task_map.keys())
    cl_task_refs = parse_checklist_task_refs(cl_path)
    spec_path = files.get("spec")

    semantic_pending = []
    if spec_path and os.path.exists(spec_path):
        spec_sections = parse_spec_sections(spec_path)
        actionable_sections = [
            section for section in spec_sections
            if section["title"] not in ("关联文档", "附录")
        ]
        if actionable_sections:
            semantic_pending.append({
                "id": "S-001",
                "category": "semantic",
                "severity": SEV_WARNING,
                "message": (
                    f'Spec has {len(actionable_sections)} section(s) that require '
                    "coverage analysis against the implementation plan"
                ),
                "file": spec_path,
                "spec_refs": [
                    {
                        "title": section["title"],
                        "line_start": section["line_start"],
                    }
                    for section in actionable_sections
                ],
            })

        attention_points = _collect_spec_attention_points(spec_path)
        if attention_points:
            semantic_pending.append({
                "id": "S-002",
                "category": "semantic",
                "severity": SEV_WARNING,
                "message": (
                    f'Spec contains {len(attention_points)} section(s) with error, '
                    "boundary, validation, or rollback concerns that need checklist coverage analysis"
                ),
                "file": spec_path,
                "spec_refs": attention_points,
            })

    for item in cl_task_refs:
        plan_title = plan_task_map.get(item["id"])
        if not plan_title:
            continue
        if _texts_semantically_close(plan_title, item["text"]):
            continue
        semantic_pending.append({
            "id": "S-003",
            "category": "semantic",
            "severity": SEV_WARNING,
            "message": (
                f'Checklist item "{item["id"]}" text may diverge from the '
                "corresponding plan task semantics"
            ),
            "file": cl_path,
            "plan_ref": item["id"],
            "checklist_ref": item["id"],
            "plan_text": plan_title,
            "checklist_text": item["text"],
        })

    for item in cl_task_refs:
        if item["id"] in plan_task_id_set:
            continue
        semantic_pending.append({
            "id": "S-004",
            "category": "semantic",
            "severity": SEV_ADVISORY,
            "message": f'Checklist item "{item["id"]}" has no matching plan task heading',
            "file": cl_path,
            "checklist_ref": item["id"],
        })

    return semantic_pending


def check_completeness(files: dict, context_yaml_path: str = None) -> List[Violation]:
    """Run M-001 through M-003 completeness checks.

    Args:
        files: dict of {role: path} for plan, checklist, etc.
        context_yaml_path: path to context.yaml for M-003.

    Returns list of Violation objects.
    """
    plan_path = files.get("plan")
    cl_path = files.get("checklist")
    if not plan_path or not cl_path:
        return []

    violations: List[Violation] = []
    plan_task_ids = _parse_plan_task_ids(plan_path)
    cl_task_refs = parse_checklist_task_refs(cl_path)
    cl_task_ids = {i["id"] for i in cl_task_refs}
    plan_phases = parse_plan_phases(plan_path)
    plan_phase_ids = {p["id"] for p in plan_phases}

    # M-001: Every plan task heading has at least one checklist item
    for task_id in plan_task_ids:
        if task_id not in cl_task_ids:
            violations.append(Violation(
                id=M_001,
                category="completeness",
                severity=SEV_ERROR,
                message=f'Plan task "{task_id}" has no checklist item',
                file=cl_path,
                plan_ref=task_id,
            ))

    # M-002: test-checklist mapping covers all impl phases
    tcl_path = files.get("test-checklist")
    if tcl_path and os.path.exists(tcl_path):
        mappings = parse_test_checklist_mappings(tcl_path)
        mapped_phases = set(mappings.keys())
        cl_sections = parse_checklist_sections(cl_path)
        cl_section_ids = {s["id"] for s in cl_sections}
        for phase_id in (plan_phase_ids | cl_section_ids):
            if phase_id not in mapped_phases:
                violations.append(Violation(
                    id=M_002,
                    category="completeness",
                    severity=SEV_WARNING,
                    message=f'Phase "{phase_id}" has no test-checklist mapping',
                    file=tcl_path,
                ))

    # M-003: context.yaml has spec field
    if "spec" not in files:
        candidate = _find_unique_spec_candidate(context_yaml_path)
        violations.append(Violation(
            id=M_003,
            category="completeness",
            severity=SEV_WARNING,
            message="context.yaml target has no spec field",
            auto_fixable=bool(candidate),
            file=context_yaml_path,
        ))

    return violations


def _has_cycle(phases: List[str], edges: List[tuple]) -> bool:
    """Detect cycle in DAG using Kahn's algorithm."""
    from collections import deque

    adj = {p: [] for p in phases}
    in_degree = {p: 0 for p in phases}
    for src, dst in edges:
        if src in adj and dst in adj:
            adj[src].append(dst)
            in_degree[dst] += 1

    queue = deque([p for p in phases if in_degree[p] == 0])
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return visited != len(phases)


def check_best_practice(files: dict) -> List[Violation]:
    """Run B-001 through B-003 best practice checks.

    Args:
        files: dict of {role: path} for plan, checklist, etc.

    Returns list of Violation objects.
    """
    plan_path = files.get("plan")
    cl_path = files.get("checklist")
    if not plan_path or not cl_path:
        return []

    violations: List[Violation] = []
    is_parallel = _is_parallel_plan(plan_path)
    cl_sections = parse_checklist_sections(cl_path)
    cl_section_entries = parse_checklist_section_entries(cl_path)

    # B-001: Section item count in 2-15 range
    entry_counts = {section["id"]: len(section["entries"]) for section in cl_section_entries}
    for section in cl_sections:
        count = entry_counts.get(section["id"], 0)
        if count < 2:
            violations.append(Violation(
                id=B_001,
                category="best_practice",
                severity=SEV_ADVISORY,
                message=f'Section "{section["id"]}" has {count} item(s) (recommended: 2-15)',
                file=cl_path,
                checklist_ref=section["id"],
            ))
        elif count > 15:
            violations.append(Violation(
                id=B_001,
                category="best_practice",
                severity=SEV_ADVISORY,
                message=f'Section "{section["id"]}" has {count} items (recommended: 2-15)',
                file=cl_path,
                checklist_ref=section["id"],
            ))

    # B-002: DAG acyclicity (parallel only)
    if is_parallel:
        dag = parse_dag_metadata(plan_path)
        if _has_cycle(dag["phases"], dag["edges"]):
            violations.append(Violation(
                id=B_002,
                category="best_practice",
                severity=SEV_ERROR,
                message="Parallel plan DAG contains a cycle",
                file=plan_path,
            ))

    # B-003: Plan contains acceptance criteria section
    with open(plan_path, "r", encoding="utf-8") as f:
        plan_content = f.read().lower()
    has_acceptance = any(term in plan_content for term in [
        "验收标准", "acceptance criteria", "验收条件",
    ])
    if not has_acceptance:
        violations.append(Violation(
            id=B_003,
            category="best_practice",
            severity=SEV_ADVISORY,
            message="Plan does not contain an acceptance criteria section",
            file=plan_path,
        ))

    return violations


# ---------------------------------------------------------------------------
# Fixers
# ---------------------------------------------------------------------------
def fix_missing_sections(plan_path: str, cl_path: str) -> List[Fix]:
    """Insert missing checklist section headings for plan phases (C-001).

    Reads plan phases and checklist sections, inserts any missing section
    headings at the end of the checklist file. Modifies cl_path in place.
    """
    plan_phases = parse_plan_phases(plan_path)
    cl_sections = parse_checklist_sections(cl_path)
    cl_section_ids = {s["id"] for s in cl_sections}
    is_parallel = _is_parallel_plan(plan_path)

    missing = [p for p in plan_phases if p["id"] not in cl_section_ids]
    if not missing:
        return []

    with open(cl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    section_starts = []
    for idx, line_raw in enumerate(lines):
        line = line_raw.rstrip("\n")
        if _match_checklist_section_heading(line):
            section_starts.append(idx)

    if section_starts:
        prefix_lines = lines[:section_starts[0]]
    else:
        prefix_lines = lines[:]

    section_blocks = {}
    section_order = []
    for pos, start in enumerate(section_starts):
        end = section_starts[pos + 1] if pos + 1 < len(section_starts) else len(lines)
        block = lines[start:end]
        header = block[0].rstrip("\n")
        match = _match_checklist_section_heading(header)
        if not match:
            continue
        section_id = match["id"]
        section_blocks[section_id] = block
        section_order.append(section_id)

    fixes: List[Fix] = []
    rebuilt = list(prefix_lines)
    seen_section_ids = set()
    for phase in plan_phases:
        section_id = phase["id"]
        if section_id in section_blocks:
            rebuilt.extend(section_blocks[section_id])
            seen_section_ids.add(section_id)
            continue

        if is_parallel:
            heading = [f"## {section_id}: {phase['title']}\n", "\n"]
        else:
            heading = [f"## Phase {section_id}: {phase['title']}\n", "\n"]
        if rebuilt and rebuilt[-1].strip():
            rebuilt.append("\n")
        rebuilt.extend(heading)
        fixes.append(Fix(
            id=C_001,
            action="insert_section",
            file=cl_path,
            description=f'Inserted missing section "{phase["id"]}: {phase["title"]}"',
            diff_preview="".join(heading).strip(),
        ))
        seen_section_ids.add(section_id)

    for section_id in section_order:
        if section_id in seen_section_ids:
            continue
        rebuilt.extend(section_blocks[section_id])

    with open(cl_path, "w", encoding="utf-8") as f:
        f.writelines(rebuilt)

    return fixes


def fix_numbering(cl_path: str) -> List[Fix]:
    """Re-number checklist section items to eliminate gaps (C-003).

    Preserves checkbox state. Modifies cl_path in place.
    """
    with open(cl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    fixes: List[Fix] = []
    current_section_id = None
    current_prefix = None
    counters = {}

    new_lines = []
    for line_raw in lines:
        line = line_raw.rstrip("\n")

        # Detect section heading to reset counter
        section = _match_checklist_section_heading(line)
        if section:
            current_section_id = section["id"]
            current_prefix = current_section_id
            new_lines.append(line_raw)
            continue
        m = _RE_CL_SUBSECTION.match(line)
        if m and current_section_id is not None:
            current_prefix = m.group(1)
            counters[current_prefix] = 0
            new_lines.append(line_raw)
            continue

        # Process checklist items
        mi = _RE_CL_TASK_ITEM.match(line)
        if mi and current_section_id is not None:
            base_prefix = current_prefix or current_section_id
            next_num = counters.get(base_prefix, 0) + 1
            counters[base_prefix] = next_num
            check_mark = mi.group(1)
            old_id = mi.group(2)
            text = mi.group(3)

            # Build new ID with subsection-aware prefix when present.
            new_id = f"{base_prefix}.{next_num}"

            if old_id != new_id:
                new_line = f"- [{check_mark}] {new_id} {text}\n"
                fixes.append(Fix(
                    id=C_003,
                    action="renumber",
                    file=cl_path,
                    description=f'Renumbered "{old_id}" → "{new_id}"',
                    diff_preview=f"- [{check_mark}] {old_id} → {new_id}",
                ))
                new_lines.append(new_line)
            else:
                new_lines.append(line_raw)
        else:
            new_lines.append(line_raw)

    if fixes:
        with open(cl_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    return fixes


def fix_header_sync(plan_path: str, cl_path: str) -> List[Fix]:
    """Sync checklist header version/date fields from plan (C-004).

    Only syncs 版本 and 更新日期. Does NOT modify 状态.
    Modifies cl_path in place.
    """
    plan_header = _parse_header(plan_path)
    cl_header = _parse_header(cl_path)

    sync_fields = ["版本", "更新日期"]
    changes = {}
    for field_name in sync_fields:
        plan_val = plan_header.get(field_name)
        cl_val = cl_header.get(field_name)
        if plan_val and cl_val and plan_val != cl_val:
            changes[field_name] = plan_val

    if not changes:
        return []

    with open(cl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    fixes: List[Fix] = []
    new_lines = []
    for line_raw in lines:
        line = line_raw.rstrip("\n")
        m = _RE_HEADER_FIELD.match(line)
        if m:
            field_name = m.group(1).strip()
            if field_name in changes:
                old_val = m.group(2).strip()
                new_val = changes[field_name]
                new_line = f"> **{field_name}**: {new_val}\n"
                new_lines.append(new_line)
                fixes.append(Fix(
                    id=C_004,
                    action="sync_header",
                    file=cl_path,
                    description=f'Synced {field_name}: "{old_val}" → "{new_val}"',
                    diff_preview=f"> **{field_name}**: {old_val} → {new_val}",
                ))
                continue
        new_lines.append(line_raw)

    with open(cl_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return fixes


def fix_missing_spec_ref(ctx_path: str, target: str, spec_dir: str,
                         plan_name: str) -> List[Fix]:
    """Add spec field to context.yaml target when unique candidate exists (M-003).

    Searches spec_dir for files matching *{plan_name}*. If exactly one
    candidate is found, adds it as the spec field. Modifies ctx_path in place.
    """
    import yaml

    with open(ctx_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    targets = data.get("spec", {}).get("targets", {})
    tgt = targets.get(target, {})

    # Already has spec
    if "spec" in tgt:
        return []

    # Search for candidate spec files
    candidates = []
    if os.path.isdir(spec_dir):
        for fname in os.listdir(spec_dir):
            if fname.endswith(".md") and plan_name in fname:
                candidates.append(fname)

    if len(candidates) != 1:
        return []  # 0 or multiple candidates — don't auto-fix

    # Build relative path from context.yaml dir to spec file
    ctx_dir = os.path.dirname(os.path.abspath(ctx_path))
    spec_abs = os.path.join(os.path.abspath(spec_dir), candidates[0])
    rel_path = os.path.relpath(spec_abs, ctx_dir)

    tgt["spec"] = rel_path
    targets[target] = tgt
    data["spec"]["targets"] = targets

    with open(ctx_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

    return [Fix(
        id=M_003,
        action="add_spec_ref",
        file=ctx_path,
        description=f'Added spec field: "{rel_path}"',
        diff_preview=f"spec: {rel_path}",
    )]


def fix_stubs(plan_path: str, cl_path: str) -> List[Fix]:
    """Generate checklist item stubs for orphan plan tasks (C-002/M-001).

    For each plan task ID that has no matching checklist item, appends a
    stub `- [ ] {id} {title}` to the correct section. Modifies cl_path in place.
    """
    plan_task_ids = _parse_plan_task_ids(plan_path)
    cl_task_refs = parse_checklist_task_refs(cl_path)
    cl_task_ids = {i["id"] for i in cl_task_refs}

    # Build task ID → title mapping from plan
    task_titles = {task["id"]: task["title"] for task in _parse_plan_tasks(plan_path)}

    # Find orphan tasks and group by section
    orphans_by_section: dict = {}
    for task_id in plan_task_ids:
        if task_id in cl_task_ids:
            continue
        # Determine which section this task belongs to
        # Task ID prefix before last dot is the section/phase ID
        parts = task_id.rsplit(".", 1)
        if len(parts) == 2:
            section_id = parts[0]
        else:
            continue
        if section_id not in orphans_by_section:
            orphans_by_section[section_id] = []
        title = task_titles.get(task_id, task_id)
        orphans_by_section[section_id].append((task_id, title))

    if not orphans_by_section:
        return []

    with open(cl_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    fixes: List[Fix] = []

    # For each section, find where it ends and insert stubs
    # Process from bottom to top to preserve line indices
    insertions = []  # (line_index, section_id)
    current_section_id = None
    section_end_line = None

    for i, line_raw in enumerate(lines):
        line = line_raw.rstrip("\n")
        section = _match_checklist_section_heading(line)
        if section:
            # If previous section had orphans, record insertion point
            if current_section_id and current_section_id in orphans_by_section:
                insertions.append((section_end_line, current_section_id))
            current_section_id = section["id"]
            section_end_line = i
        # Track last content line in section
        if current_section_id is not None:
            if line.strip():
                section_end_line = i

    # Handle last section
    if current_section_id and current_section_id in orphans_by_section:
        insertions.append((section_end_line, current_section_id))

    # Apply insertions from bottom to top
    for insert_line, section_id in reversed(insertions):
        orphans = orphans_by_section[section_id]
        stub_lines = []
        for task_id, title in orphans:
            stub = f"- [ ] {task_id} {title}\n"
            stub_lines.append(stub)
            fixes.append(Fix(
                id=C_002,
                action="insert_stub",
                file=cl_path,
                description=f'Inserted stub for "{task_id}" in section "{section_id}"',
                diff_preview=stub.strip(),
            ))
        # Insert after the last content line of the section
        for j, stub in enumerate(stub_lines):
            lines.insert(insert_line + 1 + j, stub)

    with open(cl_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return fixes


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------
_CATEGORY_TITLES = {
    "consistency": "Consistency",
    "completeness": "Completeness",
    "best_practice": "Best Practice",
}

_SEV_LABELS = {
    SEV_ERROR: "ERROR",
    SEV_WARNING: "WARN",
    SEV_ADVISORY: "INFO",
}


def format_report(violations: List[Violation],
                  semantic_pending: List[dict] = None,
                  extended_findings: List[dict] = None) -> str:
    """Format violations as human-readable report grouped by category."""
    lines: List[str] = []

    # Group by category
    by_category: dict = {}
    for v in violations:
        by_category.setdefault(v.category, []).append(v)

    for cat in ["consistency", "completeness", "best_practice"]:
        vs = by_category.get(cat, [])
        if not vs:
            continue
        title = _CATEGORY_TITLES.get(cat, cat)
        lines.append(f"## {title} ({len(vs)} issue{'s' if len(vs) != 1 else ''})")
        for v in vs:
            label = _SEV_LABELS.get(v.severity, v.severity.upper())
            fixable = " [auto-fixable]" if v.auto_fixable else ""
            lines.append(f"  - [{v.id}] {label:<5} {v.message}{fixable}")
        lines.append("")

    # Extended findings (separate section, not counted in total)
    if extended_findings:
        lines.append(f"## Extended Findings (LLM discretionary)")
        for ef in extended_findings:
            sev = ef.get("severity", "advisory").upper()
            lines.append(f"  - [{ef['id']}] {sev} {ef['message']}")
            if ef.get("basis"):
                lines.append(f"    basis: {ef['basis']}")
        lines.append("")

    if semantic_pending:
        lines.append(
            f"## Semantic Pending ({len(semantic_pending)} issue{'s' if len(semantic_pending) != 1 else ''})"
        )
        for item in semantic_pending:
            label = _SEV_LABELS.get(item.get("severity", SEV_ADVISORY), "INFO")
            lines.append(f"  - [{item['id']}] {label:<5} {item['message']}")
        lines.append("")

    # Summary
    total = len(violations)
    error_count = sum(1 for v in violations if v.severity == SEV_ERROR)
    warn_count = sum(1 for v in violations if v.severity == SEV_WARNING)
    adv_count = sum(1 for v in violations if v.severity == SEV_ADVISORY)
    fixable_count = sum(1 for v in violations if v.auto_fixable)
    semantic_count = len(semantic_pending or [])

    lines.append("## Summary")
    lines.append(
        f"  total: {total} | error: {error_count} | warning: {warn_count} | advisory: {adv_count} | semantic_pending: {semantic_count}"
    )
    lines.append(f"  auto-fixable: {fixable_count}")
    if extended_findings:
        lines.append(f"  extended_total: {len(extended_findings)}")

    return "\n".join(lines) + "\n"


def format_json(violations: List[Violation], plan: str = "",
                target: str = "",
                semantic_pending: List[dict] = None,
                extended_findings: List[dict] = None) -> str:
    """Format violations as JSON matching spec §6.3 schema."""
    import json

    total = len(violations)
    error_count = sum(1 for v in violations if v.severity == SEV_ERROR)
    warn_count = sum(1 for v in violations if v.severity == SEV_WARNING)
    adv_count = sum(1 for v in violations if v.severity == SEV_ADVISORY)
    fixable_count = sum(1 for v in violations if v.auto_fixable)
    semantic_count = len(semantic_pending or [])

    violation_dicts = []
    for v in violations:
        violation_dicts.append({
            "id": v.id,
            "category": v.category,
            "severity": v.severity,
            "message": v.message,
            "auto_fixable": v.auto_fixable,
            "file": v.file,
            "plan_ref": v.plan_ref,
            "checklist_ref": v.checklist_ref,
        })

    fix_candidates = []
    for v in violations:
        if v.auto_fixable:
            fix_candidates.append({
                "id": v.id,
                "action": f"fix_{v.id.lower().replace('-', '_')}",
                "file": v.file,
                "preview": v.message,
            })

    data = {
        "plan": plan,
        "target": target,
        "level": "L1",
        "violations": violation_dicts,
        "summary": {
            "total": total,
            "error": error_count,
            "warning": warn_count,
            "advisory": adv_count,
            "semantic_pending": semantic_count,
            "auto_fixable": fixable_count,
        },
        "semanticPending": semantic_pending or [],
        "fixCandidates": fix_candidates,
        "extendedFindings": extended_findings or [],
    }

    return json.dumps(data, ensure_ascii=False, indent=2)


def build_review_result(files: dict, context_yaml_path: str = None,
                        agent_md_path: str = None) -> dict:
    """Build the full review payload used by text/json formatters and CLI."""
    violations: List[Violation] = []
    violations.extend(check_consistency(files, agent_md_path))
    violations.extend(check_completeness(files, context_yaml_path))
    violations.extend(check_best_practice(files))
    semantic_pending = collect_semantic_pending(files)

    fix_candidates = [
        {
            "id": v.id,
            "action": f"fix_{v.id.lower().replace('-', '_')}",
            "file": v.file,
            "preview": v.message,
        }
        for v in violations
        if v.auto_fixable
    ]

    return {
        "violations": violations,
        "semantic_pending": semantic_pending,
        "fix_candidates": fix_candidates,
        "summary": {
            "total": len(violations),
            "error": sum(1 for v in violations if v.severity == SEV_ERROR),
            "warning": sum(1 for v in violations if v.severity == SEV_WARNING),
            "advisory": sum(1 for v in violations if v.severity == SEV_ADVISORY),
            "semantic_pending": len(semantic_pending),
            "auto_fixable": sum(1 for v in violations if v.auto_fixable),
        },
    }


def format_fix_result(applied: List[Fix], skipped: list,
                      post_check: dict) -> str:
    """Format fix result as three-section output."""
    lines: List[str] = []

    # Section 1: Applied
    lines.append("## Applied (--fix)")
    if applied:
        # Group by file
        by_file: dict = {}
        for f in applied:
            by_file.setdefault(f.file, []).append(f)
        for fpath, fixes in by_file.items():
            lines.append(f"  {fpath}:")
            for f in fixes:
                lines.append(f"    - [{f.id}] {f.action}: {f.description}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Section 2: Skipped
    lines.append("## Skipped (needs LLM)")
    if skipped:
        for s in skipped:
            lines.append(f"  - [{s['id']}] {s['message']}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Section 3: Post-fix Verification
    lines.append("## Post-fix Verification")
    error_now = post_check.get("error", 0)
    warn_now = post_check.get("warning", 0)
    adv_now = post_check.get("advisory", 0)
    was_error = post_check.get("was_error", error_now)
    was_warning = post_check.get("was_warning", warn_now)
    lines.append(
        f"  Re-check: error: {error_now} (was {was_error}) | "
        f"warning: {warn_now} (was {was_warning}) | advisory: {adv_now}"
    )
    remaining = error_now + warn_now + adv_now
    lines.append(f"  Remaining: {remaining} issues")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    """CLI entry point for review_plan.py."""
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="L1 document review: deterministic checks and fixes"
    )
    parser.add_argument("--context", required=True, help="context.yaml path")
    parser.add_argument("--target", required=True, help="target name")
    parser.add_argument("--files-json", required=True,
                        help="validate_context.py output JSON path")
    parser.add_argument("--check", action="store_true", help="run checks")
    parser.add_argument("--fix", action="store_true", help="apply fixes")
    parser.add_argument("--json", action="store_true",
                        help="JSON output (--check only)")
    parser.add_argument("--agent-md", default=None,
                        help="AGENTS.md path for C-005")

    args = parser.parse_args()

    # Validate mutual exclusion
    if args.check and args.fix:
        print("ERROR: --check and --fix are mutually exclusive", file=sys.stderr)
        sys.exit(2)
    if not args.check and not args.fix:
        print("ERROR: must specify --check or --fix", file=sys.stderr)
        sys.exit(2)

    # Load files.json
    if not os.path.exists(args.files_json):
        print(f"ERROR: --files-json not found: {args.files_json}", file=sys.stderr)
        sys.exit(2)
    with open(args.files_json, "r", encoding="utf-8") as f:
        files_data = json.load(f)

    # Build role → path mapping
    files = {}
    for entry in files_data.get("files", []):
        role = entry.get("role")
        path = entry.get("path")
        if role and path:
            files[role] = path

    if "plan" not in files or "checklist" not in files:
        print("ERROR: files.json must contain plan and checklist roles",
              file=sys.stderr)
        sys.exit(2)

    # Verify files exist
    for role, path in files.items():
        if not os.path.exists(path):
            print(f"ERROR: {role} file not found: {path}", file=sys.stderr)
            sys.exit(2)

    if args.check:
        review = build_review_result(
            files,
            context_yaml_path=args.context,
            agent_md_path=args.agent_md,
        )
        violations = review["violations"]
        semantic_pending = review["semantic_pending"]

        if args.json:
            # Extract plan name from context
            plan_name = ""
            if os.path.exists(args.context):
                import yaml
                with open(args.context, "r", encoding="utf-8") as f:
                    ctx = yaml.safe_load(f)
                plan_name = ctx.get("metadata", {}).get("name", "")
            print(format_json(
                violations,
                plan=plan_name,
                target=args.target,
                semantic_pending=semantic_pending,
            ))
        else:
            print(format_report(violations, semantic_pending=semantic_pending))

        sys.exit(1 if violations or semantic_pending else 0)

    elif args.fix:
        plan_path = files["plan"]
        cl_path = files["checklist"]

        # Collect pre-fix violation counts
        pre_review = build_review_result(
            files,
            context_yaml_path=args.context,
            agent_md_path=args.agent_md,
        )
        pre_violations = pre_review["violations"]
        was_error = sum(1 for v in pre_violations if v.severity == SEV_ERROR)
        was_warning = sum(1 for v in pre_violations if v.severity == SEV_WARNING)

        # Apply fixes
        applied: List[Fix] = []
        applied.extend(fix_missing_sections(plan_path, cl_path))
        applied.extend(fix_numbering(cl_path))
        applied.extend(fix_header_sync(plan_path, cl_path))
        applied.extend(fix_stubs(plan_path, cl_path))

        # Fix spec ref if applicable
        if args.context and os.path.exists(args.context):
            import yaml
            with open(args.context, "r", encoding="utf-8") as f:
                ctx = yaml.safe_load(f)
            plan_name = ctx.get("metadata", {}).get("name", "")
            spec_dir = os.path.join(os.path.dirname(args.context), "..", "..", "spec")
            applied.extend(
                fix_missing_spec_ref(args.context, args.target, spec_dir, plan_name)
            )

        # Post-fix re-check
        post_review = build_review_result(
            files,
            context_yaml_path=args.context,
            agent_md_path=args.agent_md,
        )
        post_violations = post_review["violations"]

        post_error = sum(1 for v in post_violations if v.severity == SEV_ERROR)
        post_warning = sum(1 for v in post_violations if v.severity == SEV_WARNING)
        post_advisory = sum(1 for v in post_violations if v.severity == SEV_ADVISORY)

        # Skipped items (non-auto-fixable violations)
        skipped = [
            {"id": v.id, "message": v.message}
            for v in pre_violations if not v.auto_fixable
        ]
        skipped.extend(pre_review["semantic_pending"])

        post_check = {
            "error": post_error,
            "warning": post_warning,
            "advisory": post_advisory,
            "was_error": was_error,
            "was_warning": was_warning,
        }

        # --fix --json ignores json flag, outputs text
        print(format_fix_result(applied, skipped, post_check))

        sys.exit(1 if post_violations or post_review["semantic_pending"] else 0)


if __name__ == "__main__":
    main()
