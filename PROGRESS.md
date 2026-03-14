# Hardware Pipeline — Progress Tracker

> **North Star:** Parse 100+ open-source KiCad projects, extract circuit design
> patterns, and build reusable templates that enable AI-driven hardware design.
>
> **This file drives autonomous work.** A loop runs every hour, reads this file,
> and continues from the current phase. Update status after completing each task.

---

## Current Phase: PHASE 4 NEARLY COMPLETE — Real IC symbols, wires, round-trip proven

**877 tests passing. 110 projects parsed. 343 clean IC families. Real multi-pin symbols for ESP32/STM32. 0 ERC errors.**

## Phase Overview

| Phase | Description | Status |
|-------|-------------|--------|
| **PHASE 1** | Build + test the parser (kiutils fixes, discovery, hierarchy, board, export) | **COMPLETE** — netlist round-trip validated on 3 pilots (0 mismatches) |
| **PHASE 2** | Clone + parse 100 projects at scale | **COMPLETE** (110/110 parsed, 779 units, 100% success) |
| **PHASE 3** | Extract circuit patterns (subcircuit clustering, decoupling rules, templates) | **MOSTLY COMPLETE** — missing Claude-powered cluster labeling (TASK-014) |
| **PHASE 4** | Build generation tools (datasheet→symbol, template instantiation, schematic gen) | **MOSTLY COMPLETE** — real IC symbols, wires, 0 ERC. Missing novel MCU test (TASK-024) |
| **PHASE 5** | Manufacturing integration (BOM, CPL, Gerber, 3D) | **NOT STARTED** (0/5 tasks) |

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

### PHASE 1 COMPLETE
All tests pass. All 10 pilot projects parse into valid JSON. No crashes on
any KiCad version (3-9). Hierarchical projects resolve correctly with
components from all sub-sheets.
Netlist round-trip validated: our parser matches kicad-cli netlist export
with 0 mismatches on nrfmicro (flat), STM32F7 FC (hierarchical), dumbpad (KiCad 9).

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
- [x] Run parser on all 110 cloned projects — **110/110 success (100%)**
- [x] Output: data/parsed/{project}/project.json — 779 design units, 290MB
- [x] Log: data/parse_report.json
- [x] Target: >90% → achieved **100%**

### PHASE 2 DONE ✓
110 projects parsed into normalized JSON. 779 design units. 100% success rate.
Parse time: 137s total.

---

## PHASE 3: Pattern Extraction

### 3.1 Subcircuit detection
- [x] Graph algorithm: for each IC, find all passives within 2 net hops
- [x] Group as subcircuit (center IC + supporting components)
- [x] Fingerprinting + clustering implemented
- [x] tests/test_subcircuits.py (20 tests)
- [x] Run on all 110 projects → 1014 subcircuits, 761 clusters
- [x] Fixed: exclude MountingHoles, switches, normalize fingerprints

### 3.2 Subcircuit clustering
- [x] Fingerprint: sorted passive type counts per IC
- [x] Cluster by fingerprint identity
- [ ] Label clusters with Claude (~$0.01/cluster)
- [x] Output: data/patterns/subcircuit_clusters.json

### 3.3 Decoupling pattern extraction
- [x] For each MCU: find all caps connected to power pins
- [x] Statistical summary per IC family — 437 families, 48,905 caps
- [x] Output: data/patterns/decoupling_rules.json
- [x] tests/test_patterns.py (79 tests)
- [x] Re-extracted: 437 → 343 families, 0 connectors remaining (improved classify_component)

### 3.4 Hierarchical sheet organization patterns
- [x] Record: sheet name → functional domains (power, mcu, comm, sensor, etc.)
- [x] Record: components per sheet, hierarchy depth distribution
- [x] Output: data/patterns/sheet_organization.json

### 3.5 Template generation
- [x] Build canonical templates from largest clusters — 30 cluster + 223 decoupling = 253 templates
- [x] Output: data/patterns/templates/ (summary + individual JSON)
- [x] Validate templates (ERC + netlist check via kicad-cli) — 253/253 validated

### PHASE 3 MOSTLY DONE
Circuit pattern database populated. 253 reusable templates generated and ERC validated.
Missing: TASK-014 (Claude-powered cluster labeling).

---

## PHASE 4: Generation Tools

### 4.1 Datasheet → structured data
- [x] PDF ingestion → pin tables, power requirements, reference circuits
- [x] Hardcoded fallbacks for ESP32-S3-WROOM-1, ESP32-C3-MINI-1, ESP32-WROOM-32
- [x] Claude CLI integration for unknown chips (untested in production)
- [x] Output: ParsedDatasheet with ChipDef, PinDef, power specs, reference circuits

### 4.2 Symbol + footprint generator
- [x] src/pipeline/symbol_gen.py — multi-unit .kicad_sym from structured pin data
- [x] Functional grouping (power, GPIO, USB, etc.)
- [x] kicad-cli validated output
- [x] tests/test_symbol_gen.py (6 tests)

### 4.3 Schematic generator
- [x] src/pipeline/schematic_gen.py — .kicad_sch from components + nets
- [x] Hierarchical sheet composition with sub-sheet refs + hierarchical labels
- [x] kicad-cli validated output
- [x] tests/test_schematic_gen.py (6 tests)
- [x] Decoupling cap auto-generation from rules (src/pipeline/decoupling_gen.py, 7 tests)

### 4.4 kicad-cli validation module
- [x] src/pipeline/validate.py — ERC, DRC, netlist export, BOM export
- [x] tests/test_validate.py (9 tests)

### 4.5 End-to-end test
- [x] "GPS tracker" → generates KiCad project with 0 ERC errors, wires for passives, spread hlabels
- [x] Template-driven decoupling cap generation (STM32F4xx bypass caps)
- [ ] Novel MCU (from datasheet PDF only) → valid project (needs Claude API for PDF parsing)

### 4.6 Known generation gaps (from 2026-03-14 audit)
- [x] Wire segments — passives now have wires connecting pins to nearby labels
- [x] Real IC symbols — chip_library.py: ESP32-S3 (36 pins), STM32F411 (48 pins), NEO-6M (10 pins)
- [x] Component placement — hierarchical labels now spread vertically (7.62mm spacing)
- [x] Missing project files — .kicad_pro, sym-lib-table, fp-lib-table now generated
- [x] ERC clean — GPS tracker now has 0 ERC errors
- [x] Netlist round-trip — our parser matches kicad-cli on 3 pilots (0 mismatches)

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
