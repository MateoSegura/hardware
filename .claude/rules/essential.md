# Essential Rules — hardware

## Project Purpose

AI-instrumented hardware design pipeline. Parses open-source KiCad projects,
extracts circuit design patterns, and enables AI-driven hardware design from
intent to manufacturing files.

## Code Style

- **Python**: ruff formatted, type hints on signatures, pathlib, f-strings
- **Shell**: `set -euo pipefail`, quote all vars, use `$(...)` not backticks

## Key Decisions

- **KiCad 9 S-expression format only** — convert everything else on ingest
- **kiutils** is the primary parsing library (sch + pcb, typed objects, KiCad 9 tested)
- **sexpdata** is the fallback for raw S-expression access
- **kicad-cli** for validation (ERC, DRC, netlist export) — runs headless
- **File-level parsing**, not KiCad IPC API — works without running KiCad instance

## Directory Structure

```
hardware/
├── docs/                  # Research, specs, thesis
│   └── thesis.md          # Master research document
├── src/pipeline/          # Core pipeline code
├── scripts/               # Acquisition, triage, validation scripts
├── tests/                 # Test suite
├── data/                  # (gitignored) Raw + parsed + pattern data
│   ├── raw/               # Cloned KiCad projects
│   ├── parsed/            # Normalized JSON per project
│   ├── patterns/          # Extracted templates + heuristics
│   └── validated/         # Validation reports
└── .devcontainer/         # Dev environment with KiCad 9 CLI
```

## Workplan Reference

See `docs/thesis.md` Section 8 for the full task list (TASK-001 through TASK-029).
Tasks are organized in phases:
1. **Foundation** (TASK-001 to TASK-010): Parser + validation loop
2. **Pattern extraction** (TASK-011 to TASK-018): Subcircuit clustering + templates
3. **Generation** (TASK-019 to TASK-024): Datasheet-to-symbol, schematic generation
4. **Manufacturing** (TASK-025 to TASK-029): Inventory, BOM, CPL, Gerber pipeline

## Validation

```bash
# Run parser validation loop on a project
python3 scripts/validate_parse.py data/raw/project_name/

# Run triage scoring on all raw projects
python3 scripts/triage.py data/raw/

# Run tests
pytest tests/
```

## Git Workflow

Same as codectl: branches + PRs, never commit to main directly.
```bash
git checkout -b <type>/<description>   # feat, fix, docs, chore, test
git commit -m "<type>(<scope>): <msg>" # max 72 chars, imperative
```
