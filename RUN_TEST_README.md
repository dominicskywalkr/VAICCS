## run_test.py — simple headless test runner

This repository includes a lightweight test runner, `run_test.py`, which
discovers files named `test_*.py` in the `test/` folder and executes each as a separate
process using the same Python interpreter. It's intended for the project's
ad-hoc/headless tests (scripts that print results and set exit codes).

Key behaviors
- Discovers `test_*.py` files in `test/` (ignores `build/`, `dist/` and
  `__pycache__`).
- Runs each test in its own subprocess and captures stdout/stderr.
- Detects obvious missing-module import errors ("No module named ...") and
  marks those tests as SKIPPED (they are reported separately and not counted
  as failures).
- Exit code: the runner exits with the number of failing tests (skipped
  tests are not counted as failures).

Quick usage

Run all tests found in `test/`:

```powershell
python run_test.py
```

Run one or more explicit tests (paths can be relative or absolute):

```powershell
python run_test.py test/test_voice_profiles_run.py
python run_test.py test/test_hance_models.py test/test_engine.py
```

Interpreting output
- The runner prints each test's stdout and (non-skipped) stderr, then a
  concise summary with counts of passed, skipped and failed tests.
- If a test prints a traceback mentioning missing imports, the runner will
  normally mark it as skipped and show the first stderr line as the skip
  reason.

CI integration (GitHub Actions example)

Below is a minimal GitHub Actions job that runs the test runner on Windows
using the system Python. Adapt to Linux/macOS by changing the runner and
installation commands.

```yaml
name: Run headless tests

on: [push, pull_request]

jobs:
  tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.x'
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          if (Test-Path requirements.txt) { python -m pip install -r requirements.txt }
          # install any optional test deps used by headless tests
          python -m pip install soundfile
      - name: Run tests
        run: python run_test.py
```

Notes and tips
- If your tests require audio devices or GUI capabilities, prefer marking
  them as optional or provide CI-friendly fallbacks (mocking or synthetic
  inputs). The runner will skip tests that error only because of missing
  Python modules, but it cannot emulate missing hardware.
- If you want more advanced behavior (per-test tags, parallel runs, or
  fixture setup/teardown), consider adopting `pytest` and writing small
  wrappers that call into the existing ad-hoc tests.

Contact
- If you want this runner extended (pre-scan for per-test requirements,
  per-test timeouts, or JUnit XML output), tell me which feature you want
  and I will add it.
