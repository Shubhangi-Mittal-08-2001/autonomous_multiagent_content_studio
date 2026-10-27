# Backend tests

- `unit/` contains isolated tests for backend functions and nodes.
- `integration/` contains HTTP API and compiled workflow tests.

Run both groups and enforce the backend coverage threshold from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m coverage run --rcfile=tests\.coveragerc -m pytest -q --basetemp .pytest-tmp
.\.venv\Scripts\python.exe -m coverage report --rcfile=tests\.coveragerc
```

The coverage configuration fails the report if line coverage falls below 95%.

Run Pylint from `backend/` with the tests-specific configuration and require a
score above 8.0/10:

```powershell
uv run pylint --rcfile=tests/.pylintrc tests --fail-under=8.1
```
