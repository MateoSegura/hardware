# Hardware Pipeline — Progress Tracker

> **North Star:** Parse 100+ open-source KiCad projects, extract circuit design
> patterns, and build reusable templates that enable AI-driven hardware design.
>
> **This file drives autonomous work.** A loop runs every hour, reads this file,
> and continues from the current phase. Update status after completing each task.

---

## Current Phase: PHASE 1 — Foundation (finishing integration), PHASE 2+3 starting in parallel

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| **PHASE 1** | Build + test the parser (kiutils fixes, discovery, hierarchy, board, export) | **COMPLETE** (228+ tests passing) |
| **PHASE 2** | Clone + parse 100 projects at scale | **IN PROGRESS** (110 cloned, triage done, bulk parse running) |
| **PHASE 3** | Extract circuit patterns (subcircuit clustering, decoupling rules, templates) | **IN PROGRESS** (subcircuit module done, awaiting bulk parsed data) |
| **PHASE 4** | Build generation tools (datasheet→symbol, template instantiation, schematic gen) | NOT STARTED |

---

## PHASE 1: Foundation (Parser + Tests)

### 1.1 Vendor kiutils + fix known issues
- [x] Vendor kiutils v1.4.8 into tools/kiutils/
- [x] Fix KiCad 8/9 tstamp→uuid rename
- [x] Fix (effects (hide yes)) syntax
- [x] Fix symbol name regex bug (_digit_digit misparse)
- [x] Fix scientific notation in S-expr parser
- [x] Add generator_version token support
- [x] Add embedded_fonts/embedded_files tolerance
- [x] Tests for all fixes (tests/test_kiutils_fixes.py)

### 1.2 Core kiutils test coverage
- [x] Schematic parsing tests (10 test cases)
- [x] Board parsing tests (6 test cases)
- [x] Cross-version tests (5 test cases)
- [x] Edge case tests (2 test cases)
- [x] conftest.py with pilot project fixtures

### 1.3 Project discovery module
- [x] src/pipeline/models.py — data model
- [x] src/pipeline/discovery.py — find all design units in a repo
- [x] tests/test_discovery.py (33 test cases)
- [x] All tests passing

### 1.4 Hierarchy walker module
- [x] src/pipeline/hierarchy.py — recursive sheet loading
- [x] Version-aware ref designator resolution (v6 vs v7+)
- [x] Power symbol detection
- [x] Sheet caching for shared sheets
- [x] tests/test_hierarchy.py (12 test cases)
- [x] All tests passing

### 1.5 Board parser + JSON export
- [x] src/pipeline/board.py — .kicad_pcb parsing
- [x] src/pipeline/export.py — JSON export
- [x] tests/test_board.py (13 test cases)
- [x] tests/test_export.py (3 test cases)
- [x] All tests passing

### 1.6 Net tracer module
- [x] src/pipeline/nets.py — net connectivity across hierarchical sheets
- [x] tests/test_nets.py (51 test cases)
- [x] All tests passing

### 1.7 Integration + review
- [x] src/pipeline/parse_project.py — unified entry point (discovery → hierarchy → board → nets → export)
- [x] tests/test_integration.py — end-to-end tests on all 10 pilots
- [x] Delete old src/pipeline/parser.py (replaced by new modules)
- [x] Run full test suite: pytest tests/ -v — 228+ tests passing
- [x] All 10 pilot projects parse without errors
- [x] Commit and push

### PHASE 1 DONE CRITERIA
All tests pass. All 10 pilot projects parse into valid JSON. No crashes on
any KiCad version (3-9). Hierarchical projects resolve correctly with
components from all sub-sheets.

---

## PHASE 2: Scale Data Collection

### 2.1 Bulk acquisition
- [x] Clone RepoRecon JSON database (~48K repos index)
- [x] Filter: stars >= 3, pushed within 3 years → 3811 candidates
- [x] Hardware keyword filter → 2118 hardware-specific candidates
- [x] Output: data/candidates.json + data/hardware_candidates.json

### 2.2 Triage scoring
- [x] Run scripts/triage.py on all 110 cloned projects — 0 errors
- [x] Rank by complexity score (top: Gameboy HW 17.0, Neotron 15.2, Antmicro 15.0)
- [x] Output: data/scored_projects.json (110 entries)
- [x] Score distribution: >15: 2, 10-15: 26, 5-10: 33, <5: 24

### 2.3 Bulk clone
- [x] Sparse checkout (KiCad files only) for top 100 by stars
- [x] Verified each repo has actual KiCad files (non-hardware repos removed)
- [x] Output: data/raw/ populated with 110 projects (10 pilot + 100 bulk)

### 2.4 Bulk parse
- [ ] Run parser on all 110 cloned projects
- [ ] Output: data/parsed/{project}/project.json for each
- [ ] Log: parse_report.json (successes, failures, edge cases)
- [ ] Target: >90% parse success rate

### PHASE 2 DONE CRITERIA
100+ projects parsed into normalized JSON. Parse success rate >90%.
Failures documented with root causes.

---

## PHASE 3: Pattern Extraction

### 3.1 Subcircuit detection
- [x] Graph algorithm: for each IC, find all passives within 2 net hops
- [x] Group as subcircuit (center IC + supporting components)
- [x] Fingerprinting + clustering implemented
- [x] tests/test_subcircuits.py
- [ ] Run on all 110 parsed projects → output subcircuits.json per project

### 3.2 Subcircuit clustering
- [ ] Fingerprint: sorted(component_types + connection_topology)
- [ ] Cluster by fingerprint similarity
- [ ] Label clusters with Claude (~$0.01/cluster)
- [ ] Output: data/patterns/clusters.json

### 3.3 Decoupling pattern extraction
- [ ] For each MCU: find all caps connected to power pins
- [ ] Statistical summary per MCU family
- [ ] Output: data/patterns/decoupling_rules.json

### 3.4 Hierarchical sheet organization patterns
- [ ] Record: sheet name → functional domains
- [ ] Record: components per sheet, sheet-to-sheet connections
- [ ] Output: data/patterns/sheet_organization.json

### 3.5 Template generation
- [ ] Build canonical templates from largest clusters
- [ ] Validate templates (ERC + netlist check via kicad-cli)
- [ ] Output: data/patterns/templates/

### PHASE 3 DONE CRITERIA
Circuit pattern database populated. At least 10 reusable templates
validated (Ethernet, USB, LDO, DCDC, IMU, GPS, etc.).

---

## PHASE 4: Generation Tools

### 4.1 Datasheet → structured data
- [ ] PDF ingestion → pin tables, power requirements, reference circuits
- [ ] Output: structured JSON per chip

### 4.2 Symbol + footprint generator
- [ ] Multi-unit .kicad_sym from structured pin data
- [ ] Functional grouping (power, GPIO, USB, etc.)

### 4.3 Schematic generator
- [ ] Template instantiation → .kicad_sch
- [ ] Hierarchical sheet composition
- [ ] Decoupling cap auto-generation

### 4.4 End-to-end test
- [ ] "GPS tracker" → valid KiCad project
- [ ] Novel MCU (from datasheet only) → valid project

---

## How To Continue (for autonomous loop)

1. Read this file to determine current phase and next incomplete task
2. Check if tests exist and are passing: `cd ~/hardware && python3 -m pytest tests/ -v 2>&1 | tail -20`
3. If tests are failing, fix the code until they pass
4. If all tasks in current phase are complete, move to next phase
5. Mark completed tasks with [x] in this file
6. Commit progress: `cd ~/hardware && git add -A && git commit -m "progress: <what was done>"`
7. If stuck on something, document the blocker in a BLOCKERS section at the bottom
8. Key files:
   - Architecture spec: docs/parser-architecture.md
   - Thesis/research: docs/thesis.md
   - Vendored kiutils: tools/kiutils/
   - Pipeline code: src/pipeline/
   - Tests: tests/
   - Pilot data: data/raw/ (10 pilot + 100 bulk cloned KiCad projects)
   - kicad-cli: /usr/bin/kicad-cli v9.0.7 — use for ERC, DRC, netlist export, BOM, Gerber
     Example: `kicad-cli sch erc file.kicad_sch --format json -o report.json`
   - Bulk parse script: `python3 -m src.pipeline.parse_project data/raw/project_name/`
