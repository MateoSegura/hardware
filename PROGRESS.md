# Hardware Pipeline — Progress Tracker

> **North Star:** Parse 100+ open-source KiCad projects, extract circuit design
> patterns, and build reusable templates that enable AI-driven hardware design.
>
> **This file drives autonomous work.** A loop runs every hour, reads this file,
> and continues from the current phase. Update status after completing each task.

---

## Current Phase: PHASE 1 — Foundation

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| **PHASE 1** | Build + test the parser (kiutils fixes, discovery, hierarchy, board, export) | **IN PROGRESS** |
| **PHASE 2** | Clone + parse 100 projects at scale | NOT STARTED |
| **PHASE 3** | Extract circuit patterns (subcircuit clustering, decoupling rules, templates) | NOT STARTED |
| **PHASE 4** | Build generation tools (datasheet→symbol, template instantiation, schematic gen) | NOT STARTED |

---

## PHASE 1: Foundation (Parser + Tests)

### 1.1 Vendor kiutils + fix known issues
- [x] Vendor kiutils v1.4.8 into tools/kiutils/
- [ ] Fix KiCad 8/9 tstamp→uuid rename
- [ ] Fix (effects (hide yes)) syntax
- [ ] Fix symbol name regex bug (_digit_digit misparse)
- [ ] Fix scientific notation in S-expr parser
- [ ] Add generator_version token support
- [ ] Add embedded_fonts/embedded_files tolerance
- [ ] Tests for all fixes (tests/test_kiutils_fixes.py)

### 1.2 Core kiutils test coverage
- [ ] Schematic parsing tests (10 test cases)
- [ ] Board parsing tests (6 test cases)
- [ ] Cross-version tests (2 test cases)
- [ ] Edge case tests (2 test cases)
- [ ] conftest.py with pilot project fixtures

### 1.3 Project discovery module
- [ ] src/pipeline/models.py — data model
- [ ] src/pipeline/discovery.py — find all design units in a repo
- [ ] tests/test_discovery.py (10 test cases)
- [ ] All tests passing

### 1.4 Hierarchy walker module
- [ ] src/pipeline/hierarchy.py — recursive sheet loading
- [ ] Version-aware ref designator resolution (v6 vs v7+)
- [ ] Power symbol detection
- [ ] Sheet caching for shared sheets
- [ ] tests/test_hierarchy.py (12 test cases)
- [ ] All tests passing

### 1.5 Board parser + JSON export
- [ ] src/pipeline/board.py — .kicad_pcb parsing
- [ ] src/pipeline/export.py — JSON export
- [ ] tests/test_board.py (10 test cases)
- [ ] tests/test_export.py (3 test cases)
- [ ] All tests passing

### 1.6 Integration + review
- [ ] Delete old src/pipeline/parser.py (replaced by new modules)
- [ ] Run full test suite: pytest tests/ -v
- [ ] All 10 pilot projects parse without errors
- [ ] Commit and push

### PHASE 1 DONE CRITERIA
All tests pass. All 10 pilot projects parse into valid JSON. No crashes on
any KiCad version (3-9). Hierarchical projects resolve correctly with
components from all sub-sheets.

---

## PHASE 2: Scale Data Collection

### 2.1 Bulk acquisition
- [ ] Clone RepoRecon JSON database (~40K repos index)
- [ ] Filter: stars >= 3, has LICENSE, pushed within 3 years
- [ ] License filter: Apache-2.0, MIT, CC-BY, CERN-OHL-P first
- [ ] GitHub API check: has both .kicad_sch + .kicad_pcb
- [ ] Output: candidates.json with ~500 qualified repos

### 2.2 Triage scoring
- [ ] Run scripts/triage.py on all candidates (regex-based, fast)
- [ ] Rank by complexity score
- [ ] Select top 100-200 for deep parsing
- [ ] Output: scored_projects.json

### 2.3 Bulk clone
- [ ] Sparse checkout (KiCad files only) for top 100-200
- [ ] Normalize: convert KiCad 5/6/7 files to v8+ format if needed
- [ ] Output: data/raw/ populated with 100+ projects

### 2.4 Bulk parse
- [ ] Run parser on all cloned projects
- [ ] Output: data/parsed/{project}/project.json for each
- [ ] Log: parse_report.json (successes, failures, edge cases)
- [ ] Target: >90% parse success rate

### PHASE 2 DONE CRITERIA
100+ projects parsed into normalized JSON. Parse success rate >90%.
Failures documented with root causes.

---

## PHASE 3: Pattern Extraction

### 3.1 Subcircuit detection
- [ ] Graph algorithm: for each IC, find all passives within 2 net hops
- [ ] Group as subcircuit (center IC + supporting components)
- [ ] Output: subcircuits.json per project

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
   - Pilot data: data/raw/ (10 cloned KiCad projects)
