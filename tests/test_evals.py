"""Structure of evals/ (no model call) and the evals_pass_rate KPI logic.

`claude plugin eval` itself costs API money and runs on demand (.github/workflows/evals.yml); these
tests only catch a malformed suite or a KPI that would break the normal PR run."""
import json, os, re, sys
import pytest, yaml
from conftest import ROOT

sys.path.insert(0, os.path.join(ROOT, "ci"))
import kpi

EVALS = os.path.join(ROOT, "evals")
CASES = sorted(d for d in os.listdir(EVALS) if os.path.isfile(os.path.join(EVALS, d, "prompt.md")))
SKILLS = set(os.listdir(os.path.join(ROOT, "skills")))
PROMPT_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome", "model",
               "max_turns", "timeout_seconds", "allowed_tools", "append_system_prompt", "env"}
GRADER_KEYS = {"regex": {"pattern", "flags", "match", "target"}, "tool_used": {"tool", "input_match", "min", "max"},
               "tool_order": {"before", "after"}, "file_exists": {"path", "exists"}, "llm": {"criteria", "focus"}}


def frontmatter(path):
    m = re.match(r"---\n(.*?)\n---\n(.*)", open(path).read(), re.S)
    assert m, f"{path}: no frontmatter"
    return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()


def graders(case):
    d = os.path.join(EVALS, case, "graders")
    return [(f, *frontmatter(os.path.join(d, f))) for f in sorted(os.listdir(d)) if f.endswith(".md")]


def test_the_four_behaviours_are_covered():
    assert {"hook-blocks-sidecar-write", "hook-allows-read", "photo-diagnose-before-edit",
            "frame-for-social-phone-check", "export-never-invents"} <= set(CASES)


@pytest.mark.parametrize("case", CASES)
def test_case_is_well_formed(case):
    meta, body = frontmatter(os.path.join(EVALS, case, "prompt.md"))
    assert set(meta) <= PROMPT_KEYS and body
    gs = graders(case)
    assert gs, "a case without a grader fails to load"
    for f, g, text in gs:
        t = g["type"]
        assert t in GRADER_KEYS, f
        assert set(g) - {"type", "weight", "arm"} <= GRADER_KEYS[t], f
        required = {"regex": "pattern", "tool_used": "tool", "file_exists": "path"}.get(t)
        assert required is None or required in g, f
        assert t != "llm" or g.get("criteria") or text, f"{f}: empty rubric"
        if "pattern" in g:
            re.compile(g["pattern"])
        for s in re.findall(r"\(\?:\[\\w-\]\+:\)\?([\w-]+)", g.get("input_match", "")):
            assert s in SKILLS, f"{f}: no skill {s}"
    cy = os.path.join(EVALS, case, "case.yaml")
    if os.path.exists(cy):
        c = yaml.safe_load(open(cy))
        assert c["schema_version"] == "1.1" and c["name"] == case
        script = (c.get("context") or {}).get("scaffold_script")
        assert script is None or os.access(os.path.join(EVALS, case, script), os.X_OK)


def test_placeholder_regex_tells_inventing_from_asking():
    pat = frontmatter(os.path.join(EVALS, "export-never-invents", "graders", "placeholders-left.md"))[0]["pattern"]
    assert re.search(pat, "Found at {location}: {species}.", re.I)
    assert re.search(pat, "Found at [location to confirm]", re.I)
    assert not re.search(pat, "Found at Yosemite: Apis mellifera.", re.I)


def test_hook_cases_need_the_fake_process_declared():
    for case in ("hook-blocks-sidecar-write", "hook-allows-read"):
        assert "needs-fake-darktable" in frontmatter(os.path.join(EVALS, case, "prompt.md"))[0]["tags"]


# ---- evals_pass_rate KPI -------------------------------------------------------------------

BASE = {"evals_pass_rate": 0.75}


def row(k, only=()):
    return {r[0]: r for r in kpi.check(k, {**BASE, "darktable_tests_run": 0, "pitfalls_covered": 0,
                                           "param_fields_confirmed": 0, "always_on_tokens_budget": 10**9}, only)[1]}


def test_kpi_is_skipped_not_failed_when_no_eval_ran(tmp_path):
    assert kpi.evals_pass_rate(str(tmp_path)) == (None, False)
    assert row({"evals_pass_rate": None, "evals_ran": False})["evals_pass_rate"][3] == "skip"


def test_kpi_fails_when_required_and_missing():
    assert row({"evals_pass_rate": None, "evals_ran": False}, ("evals_pass_rate",))["evals_pass_rate"][3] == "FAIL"


def test_kpi_reads_the_eval_result(tmp_path):
    doc = {"aggregates": {"casesPassed": 4, "casesTotal": 5}}
    (tmp_path / "evals-result.json").write_text(json.dumps(doc))
    assert kpi.evals_pass_rate(str(tmp_path)) == (0.8, True)
    assert row({"evals_pass_rate": 0.8, "evals_ran": True})["evals_pass_rate"][3] == "pass"
    assert row({"evals_pass_rate": 0.5, "evals_ran": True})["evals_pass_rate"][3] == "FAIL"


def test_partial_eval_run_has_no_rate(tmp_path):
    doc = {"partial": True, "partialReason": "cost_ceiling", "aggregates": {"casesPassed": 1, "casesTotal": 5}}
    (tmp_path / "evals-result.json").write_text(json.dumps(doc))
    assert kpi.evals_pass_rate(str(tmp_path)) == (None, True)
    assert row({"evals_pass_rate": None, "evals_ran": True})["evals_pass_rate"][3] == "FAIL"
