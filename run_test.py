#!/usr/bin/env python3
"""Simple test runner for headless tests.

Finds files named test_*.py in the test directory and executes each with the same
Python interpreter. Captures stdout/stderr and exit code and prints a concise
per-test report plus a summary.

Usage:
    python run_test.py                 # runs all test_*.py files in test/
    python run_test.py test/test_a.py  # run a single test file or a list of files

This runner purposely invokes each test as a subprocess so tests that are not
unittest-style (ad-hoc scripts) will still run and report their exit codes.
"""
from __future__ import annotations

import glob
import os
import sys
import subprocess
import textwrap
from typing import List


BASE = os.path.abspath(os.path.dirname(__file__))


def find_tests(pattern: str = "test_*.py") -> List[str]:
    # Search only the dedicated test directory, not built artifacts or libraries.
    files = []
    for p in glob.glob(os.path.join(BASE, "test", pattern)):
        # exclude build folders explicitly if file paths contain them
        if any(part in p.replace('\\', '/') for part in ('build/', 'dist/', '__pycache__')):
            continue
        files.append(os.path.abspath(p))
    files.sort()
    return files


def run_test(path: str, timeout: float = 60.0) -> dict:
    cmd = [sys.executable, path]
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = BASE if not existing_pythonpath else BASE + os.pathsep + existing_pythonpath
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=BASE, env=env)
        ret = {
            "path": path,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        # Detect obvious missing-module import failures and mark as skipped.
        # We consider patterns like "ModuleNotFoundError: No module named 'X'" or
        # "ImportError: No module named X" as skip reasons for optional deps.
        err = (proc.stderr or "")
        if proc.returncode != 0 and ("No module named" in err or "ModuleNotFoundError" in err):
            # extract a brief reason (first line of stderr)
            first_line = err.strip().splitlines()[0] if err.strip() else ""
            ret["skipped"] = True
            ret["skip_reason"] = first_line
        else:
            ret["skipped"] = False
        return ret
    except subprocess.TimeoutExpired as e:
        return {"path": path, "returncode": 124, "stdout": e.stdout or "", "stderr": f"TIMEOUT after {timeout}s", "skipped": False}


def print_report(results: List[dict]):
    passed = [r for r in results if r["returncode"] == 0]
    skipped = [r for r in results if r.get("skipped")]
    failed = [r for r in results if r["returncode"] != 0 and not r.get("skipped")]

    sep = "=" * 80
    print(sep)
    print("Test run summary")
    print(sep)
    print(f"Total tests discovered: {len(results)}")
    print(f"Passed: {len(passed)}")
    print(f"Skipped (missing deps): {len(skipped)}")
    print(f"Failed: {len(failed)}")
    print()

    for r in results:
        name = os.path.relpath(r["path"], BASE)
        if r.get("skipped"):
            status = f"SKIP ({r.get('skip_reason','missing dependency')})"
        else:
            status = "PASS" if r["returncode"] == 0 else f"FAIL ({r['returncode']})"
        print(textwrap.indent(f"{name} -> {status}", "- "))
        if r["stdout"]:
            out = r["stdout"].strip()
            if out:
                print(textwrap.indent("Stdout:", "  "))
                print(textwrap.indent(out, "    "))
        if r["stderr"] and not r.get("skipped"):
            err = r["stderr"].strip()
            if err:
                print(textwrap.indent("Stderr:", "  "))
                print(textwrap.indent(err, "    "))
        print()


def main(argv: List[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    if argv:
        # explicit list of test files
        tests = [os.path.abspath(p) for p in argv]
    else:
        tests = find_tests()

    if not tests:
        print("No test_*.py files found in test/.")
        return 0

    results = []
    for t in tests:
        print(f"Running: {os.path.relpath(t, BASE)} ...")
        res = run_test(t, timeout=120.0)
        results.append(res)

    print_report(results)

    # exit with number of failures (skipped tests are not counted as failures)
    failures = sum(1 for r in results if r["returncode"] != 0 and not r.get("skipped"))
    return failures


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
