#!/usr/bin/env python3
"""Compute the plugin KPIs from CI artifacts and enforce the thresholds in ci/kpi-baseline.json.

    python3 ci/kpi.py ARTIFACT_DIR [--update-baseline] [--only KPI]

ARTIFACT_DIR holds pytest-*.json (written by tests/conftest.py), plugin-details.txt
(`claude plugin details` output), validate.txt (`claude plugin validate` output) and, only after a
manual evals run, evals-result.json (`claude plugin eval --json`). evals_pass_rate is skipped
(neither pass nor fail) when evals-result.json is absent, because evals cost API money and run
on demand; with `--only evals_pass_rate` (the evals workflow) its absence fails like any KPI.
Writes kpis.json, prints a markdown table (appended to $GITHUB_STEP_SUMMARY when set) and
exits 1 when a KPI misses its threshold. A KPI that could not be measured fails too:
an empty check is not a passing check.
"""
import glob, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_tests(d):
    res = []
    for f in sorted(glob.glob(os.path.join(d, "**", "pytest-*.json"), recursive=True)):
        res += json.load(open(f))
    return res


def pitfall_ids():
    return re.findall(r"^\| (P\d+) \|", open(os.path.join(ROOT, "docs", "pitfalls.md")).read(), re.M)


def evals_pass_rate(d):
    """(cases passed / cases, ran) from the `claude plugin eval --json` document evals-result.json.
    ran is False when no such file exists (evals run on demand only, see .github/workflows/evals.yml).
    A partial run (cost ceiling, auth failure, interruption) has no rate: None."""
    files = glob.glob(os.path.join(d, "**", "evals-result.json"), recursive=True)
    if not files:
        return None, False
    doc = json.load(open(files[0]))
    agg = doc.get("aggregates") or {}
    if doc.get("partial") or not agg.get("casesTotal"):
        return None, True
    return round(agg["casesPassed"] / agg["casesTotal"], 4), True


def compute(d):
    tests = load_tests(d)
    passed = {t["test"] for t in tests if t["outcome"] == "passed"}
    failed = [t["test"] for t in tests if t["outcome"] == "failed"]
    dt = [t for t in tests if t["darktable"]]
    k = {}
    k["tests_total"] = len(tests)
    k["tests_failed"] = len(failed)
    # the same test runs on several OSes: count distinct names, not records, on both sides
    k["tests_pass_rate"] = round(len(passed) / len({t["test"] for t in tests}), 4) if tests else None
    k["darktable_tests_run"] = sum(1 for t in dt if t["outcome"] != "skipped")
    k["darktable_tests_run_by_os"] = {}  # informational; the ratchet applies to the total
    for t in dt:
        if t["outcome"] != "skipped":
            os_ = t.get("platform", "unknown")
            k["darktable_tests_run_by_os"][os_] = k["darktable_tests_run_by_os"].get(os_, 0) + 1
    ids = pitfall_ids()
    covered = sorted({p for t in tests if t["outcome"] == "passed" for p in t["pitfalls"]} & set(ids))
    k["pitfalls_documented"] = len(ids)
    k["pitfalls_covered"] = len(covered)
    k["pitfalls_uncovered"] = sorted(set(ids) - set(covered))
    mods = json.load(open(os.path.join(ROOT, "tools", "modules.json")))
    fields = [f for m, v in mods.items() if not m.startswith("_") for f in v["fields"]]
    norm = lambda s: s.split("tests/", 1)[-1]
    passed_norm = {norm(p) for p in passed}
    k["param_fields_known"] = len(fields)
    k["param_fields_confirmed"] = sum(1 for f in fields if f["test"] and norm(f["test"]) in passed_norm)
    det = os.path.join(d, "plugin-details.txt")
    m = re.search(r"Always-on:\s*~?([\d.,]+)\s*(k?)\s*tok", open(det).read()) if os.path.exists(det) else None
    k["always_on_tokens"] = (round(float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1))
                             if m else None)
    val = os.path.join(d, "validate.txt")
    k["manifests_valid"] = (open(val).read().count("Validation passed") >= 2) if os.path.exists(val) else None
    k["evals_pass_rate"], k["evals_ran"] = evals_pass_rate(d)
    k["_failed_tests"] = failed
    return k


RULES = {  # kpi: (comparison, baseline key)
    "tests_pass_rate": ("==", 1.0),
    "tests_failed": ("==", 0),
    "darktable_tests_run": (">=", "darktable_tests_run"),
    "pitfalls_covered": (">=", "pitfalls_covered"),
    "param_fields_confirmed": (">=", "param_fields_confirmed"),
    "always_on_tokens": ("<=", "always_on_tokens_budget"),
    "manifests_valid": ("==", True),
    "evals_pass_rate": (">=", "evals_pass_rate"),
}


def check(k, base, only=()):
    """only: restrict to these KPIs and require them (the evals workflow). Without it, a KPI that
    exists only on demand (evals_pass_rate) is skipped when it did not run, instead of failing."""
    rows, ok = [], True
    for name, (op, ref) in RULES.items():
        if only and name not in only:
            continue
        if name == "evals_pass_rate" and not k["evals_ran"] and not only:
            rows.append((name, "not run", "on demand only", "skip"))
            continue
        target = base[ref] if isinstance(ref, str) else ref
        val = k.get(name)
        good = val is not None and {"==": val == target, ">=": val >= target, "<=": val <= target}[op]
        ok &= good
        rows.append((name, val, f"{op} {target}", "pass" if good else "FAIL"))
    return ok, rows


def main():
    d = sys.argv[1]
    base_path = os.path.join(HERE, "kpi-baseline.json")
    base = json.load(open(base_path))
    only = sys.argv[sys.argv.index("--only") + 1:][:1] if "--only" in sys.argv else []
    k = compute(d)
    ok, rows = check(k, base, only)
    json.dump(k, open(os.path.join(d, "kpis.json"), "w"), indent=1)
    md = ["## darkroom-claude KPIs", "", "| KPI | Value | Threshold | Result |", "|---|---|---|---|"]
    md += [f"| {n} | {v} | {t} | {r} |" for n, v, t, r in rows]
    if not only:
        md += ["", f"Pitfalls without a passing test: {', '.join(k['pitfalls_uncovered']) or 'none'}",
               f"Parameter fields confirmed: {k['param_fields_confirmed']} / {k['param_fields_known']}",
               f"darktable tests run per OS: {k['darktable_tests_run_by_os'] or 'none'}"]
    if k["_failed_tests"] and not only:
        md += ["", "Failed tests:"] + [f"- `{t}`" for t in k["_failed_tests"]]
    text = "\n".join(md) + "\n"
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write(text)
    if "--update-baseline" in sys.argv and ok:
        for key in ("darktable_tests_run", "pitfalls_covered", "param_fields_confirmed", "evals_pass_rate"):
            if k[key] is not None and (not only or key in only):
                base[key] = max(base[key], k[key])
        json.dump(base, open(base_path, "w"), indent=2); open(base_path, "a").write("\n")
        print("baseline raised")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
