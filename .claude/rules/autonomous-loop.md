# Autonomous Work Loop

When invoked via `/loop` or when this session starts, follow this protocol:

## On Every Invocation

1. **Read PROGRESS.md** — this is the single source of truth
2. **Run tests** — `cd ~/hardware && python3 -m pytest tests/ -v 2>&1`
3. **Assess state:**
   - If tests are failing → fix the failing tests/code first
   - If tests pass → find the next unchecked `[ ]` task in PROGRESS.md
   - If a phase is complete → move to the next phase
4. **Do the work** — implement, test, fix
5. **Update PROGRESS.md** — mark completed tasks with `[x]`
6. **Commit** — `git add -A && git commit -m "progress: <summary>"`
7. **Push** — `git push`

## Quality Standards

- All code must have tests (TDD — write test first, then implementation)
- Tests use REAL KiCad files from data/raw/ — NO mocks
- Python code must be clean: type hints, docstrings on public functions, pathlib for paths
- Run `ruff check src/ tests/` before committing

## Key Context

- Vendored kiutils is in tools/kiutils/ — this is OUR copy to fix and extend
- Parser architecture spec is in docs/parser-architecture.md
- Full research is in docs/thesis.md
- Pilot projects (10 real KiCad designs) are in data/raw/
- The pipeline code goes in src/pipeline/
