# Hardware Design Intelligence Pipeline — Thesis & Research Log

> **Date:** 2026-03-14
> **Status:** Active research → prototyping
> **Goal:** Build an AI-instrumented pipeline that ingests open-source KiCad
> designs, extracts circuit design patterns, and enables AI-driven hardware
> design from intent to manufacturing files.

---

## 1. Vision

Use AI (Claude) to design hardware. Not toy circuits — real products with
real MCUs (ESP32, Nordic nRF, NXP i.MX RT, STM32), real peripherals (GPS,
cellular modems, IMUs, SD cards), and real manufacturing output (Gerbers,
BOM, pick-and-place files for a LumenPNP machine).

KiCad is the only fully programmatic EDA. Its files are S-expression text,
its CLI runs headless, and its formats are stable across versions. This
makes it the only viable foundation for AI-driven hardware design.

### The End State

```
"Design me a GPS tracker"
    → Block diagram decomposition
    → Component selection from inventory
    → Schematic generation (hierarchical, multi-sheet)
    → Symbol + footprint generation for any chip (from datasheet)
    → PCB layout (coarse placement + routing)
    → Validation (DRC, ERC, BOM check)
    → Manufacturing output (Gerbers, CPL for LumenPNP, BOM)
```

### What's Software-Solvable vs What's Not

| Category | Feasibility | Notes |
|----------|------------|-------|
| Component selection from inventory | HIGH | Constraint satisfaction / DB lookup |
| Schematic generation from netlist | HIGH | S-expression is structured text |
| Circuit design for known topologies | MEDIUM-HIGH | Well-documented reference designs |
| Multi-unit symbol generation | HIGH | KiPart or direct S-expr from datasheet CSV |
| Decoupling cap generation | HIGH | Rules engine from datasheet tables |
| BOM/CPL/Gerber pipeline | HIGH | kicad-cli does export, we match to inventory |
| DRC/ERC automation | HIGH | kicad-cli runs headless, outputs JSON |
| Hierarchical schematic templates | HIGH | Python functions emitting S-expressions |
| Component placement on PCB | PARTIAL | Coarse floorplanning yes, fine placement needs review |
| PCB routing | LOW-MEDIUM | Freerouting for simple boards, fails on DDR/RF |
| Novel analog circuit design | LOW | Can replicate known topologies, not innovate |
| EMC/EMI compliance prediction | OUT OF REACH | Needs full-wave simulation |
| Thermal design without simulation | OUT OF REACH | Rules of thumb only |

---

## 2. The Data Problem

### Why We Need Data

Circuit design patterns are learned from real designs, not invented. We need
a corpus of complex, professionally-designed KiCad projects to:

1. Build and validate a KiCad file parser
2. Extract reusable circuit templates (Ethernet, USB, power supply, etc.)
3. Learn decoupling cap patterns per MCU family
4. Learn hierarchical schematic organization conventions
5. Learn component placement heuristics
6. Build a pin-name-to-function classifier

### The Datasheet-to-Symbol Bridge

**Critical insight:** Even if a chip has zero open-source KiCad designs, we
can still support it. The scraped designs teach us *patterns*. A datasheet
parser applies those patterns to *any* chip. Cost: ~$1-2 in LLM tokens per
datasheet (reading 300-page PDF, extracting pin tables, power requirements,
reference circuits).

This means Nordic nRF, NXP i.MX RT, and STM32H7 — which have few KiCad
designs — are still fully supported.

---

## 3. Tool Landscape Assessment

### KiCad Parsing Libraries (Tested 2026-03-14)

All tested on Python 3.12.3, against KiCad 6 (HackRF) and KiCad 9 files.

| Library | Version | Schematic | PCB | KiCad 9 | Speed (245 comp) | Verdict |
|---------|---------|-----------|-----|---------|-------------------|---------|
| **kiutils** | 1.4.8 | Yes | Yes | Yes | 10ms | **PRIMARY — use this** |
| kicad-sch-api | 0.5.6 | Yes | No | Yes | 73ms | Best high-level API, schematic-only |
| kicad-skip | 0.2.5 | Yes | No | Yes | 38ms | Thin wrapper, stderr spam |
| sexpdata | 1.0.2 | Yes | Yes | Yes | 108ms | Raw S-expr, no semantics |

**Decision: Use `kiutils` as primary parser.** Typed Python objects, both
schematic + PCB, fast, no stderr spam, handles KiCad 6-9.

Fallback plan: `sexpdata` for raw S-expression access if kiutils chokes on
edge cases.

### Code-First EDA Tools

| Tool | Status | Can Handle Complex Designs? | Notes |
|------|--------|---------------------------|-------|
| JITX | Commercial, active | Yes — defense customers, 30+ layer boards | Proprietary, expensive |
| atopile | Open-source, v0.12.5 | No — "low to medium complexity" | Clean language, immature |
| SKiDL | Open-source, v2.2.1 | Netlist only — destroys layout on re-run | Solo maintainer, stagnant |
| Circuit-Synth | Open-source, early | Netlist only — has bi-directional KiCad sync | Right architecture, early |

**None of these solve our problem.** We're building the missing layer:
parsing real designs → extracting patterns → generating new designs.

### KiCad CLI (kicad-cli)

Available in KiCad 9. Key commands for our pipeline:

| Command | Use |
|---------|-----|
| `kicad-cli sch erc` | Electrical rules check → JSON report |
| `kicad-cli sch export netlist` | Netlist export for round-trip validation |
| `kicad-cli sch export bom` | BOM with configurable fields |
| `kicad-cli pcb drc` | Design rules check → JSON report |
| `kicad-cli pcb export gerbers` | Gerber output |
| `kicad-cli pcb export pos` | Pick-and-place position file (for LumenPNP) |
| `kicad-cli pcb export drill` | Drill files |

**Status:** Not installed on dev machine. Must be added to devcontainer.

---

## 4. KiCad File Format Reference

### Target Format

**KiCad 9 S-expression only.** Version token: `20250114` or later.
Convert any KiCad 5/6/7/8 files on ingest by opening in KiCad 9 and saving.
One format, one parser.

### Project File Anatomy

```
project/
├── project.kicad_pro         # Project settings (JSON-like)
├── project.kicad_sch         # Root schematic (S-expression)
├── sub_sheet_1.kicad_sch     # Hierarchical sub-sheets
├── sub_sheet_2.kicad_sch
├── project.kicad_pcb         # PCB layout (S-expression)
├── sym-lib-table             # Local symbol library table
├── fp-lib-table              # Local footprint library table
└── libs/                     # Project-local libraries
    ├── custom.kicad_sym      # Custom symbols
    └── custom.pretty/        # Custom footprints
        └── part.kicad_mod
```

### Key S-Expression Structures

**Component instance in schematic:**
```lisp
(symbol
  (lib_id "Device:R")
  (at 152.4 101.6 0)
  (unit 1)
  (uuid "component-uuid")
  (property "Reference" "R1" ...)
  (property "Value" "10k" ...)
  (property "Footprint" "Resistor_SMD:R_0402_1005Metric" ...)
  (pin "1" (uuid "pin1-uuid"))
  (pin "2" (uuid "pin2-uuid"))
  (instances (project "Name" (path "/root-uuid" (reference "R1") (unit 1))))
)
```

**Hierarchical sheet reference:**
```lisp
(sheet
  (at 100 50) (size 30 20)
  (uuid "sheet-uuid")
  (property "Sheetname" "PowerSupply" ...)
  (property "Sheetfile" "power_supply.kicad_sch" ...)
  (pin "VCC" input (at 130 55) (uuid "pin-uuid"))
  (pin "GND" input (at 130 65) (uuid "pin-uuid"))
)
```

**Net connectivity model:**

| Label Type | Scope | S-expression |
|------------|-------|-------------|
| `(label ...)` | Local — current sheet only | Same name on same sheet = connected |
| `(global_label ...)` | Global — entire design | Same name across ALL sheets |
| `(hierarchical_label ...)` | Parent-child | Matches parent sheet's pin name |

### Multi-Unit Symbol Structure

In `.kicad_sym`, multi-unit symbols use naming convention `NAME_UNIT_STYLE`:
- Unit 0 = common to all units (shared graphics)
- Unit 1+ = specific functional unit
- Style 1 = normal, Style 2 = De Morgan

For a BGA MCU like i.MX RT1050 (196 pins), split into:
- Unit 1: Core power (VDD, VSS, DCDC)
- Unit 2: SEMC/SDRAM interface
- Unit 3: Ethernet RMII/MDIO
- Unit 4: USB OTG/PHY
- Unit 5: FlexSPI/boot
- Unit 6: GPIO banks
- Unit 7: JTAG, crystal, PLL

---

## 5. Data Sources

### Tier 1: Professional Engineering (best organized, most complex)

| Source | URL | ~Projects | Complexity | License | Key Value |
|--------|-----|-----------|------------|---------|-----------|
| **Antmicro** | github.com/antmicro | 30-50+ | Very High | Apache 2.0 | FPGA/SoM carrier boards, hierarchical, custom libs |
| **Olimex** | github.com/OLIMEX | 20+ | Simple → Very High | CERN OHL v2 | iMX8 SBCs, ESP32 boards, 20+ years OSHW |
| **Great Scott Gadgets** | github.com/greatscottgadgets | 5-8 | Very High | GPL v2 | HackRF (7.7K stars), RF design, controlled impedance |
| **MNT Research** | source.mnt.re/reform/reform | 7 PCBs | Very High | CERN OHL v2 | Full laptop, DDR routing, multi-board system |
| **System76** | github.com/system76 | 3-5 | Medium → Very High | GPL v3 | Keyboard + laptop motherboard |

### Tier 2: Commercial Products

| Source | URL | MCU/SoC | Peripherals | License |
|--------|-----|---------|-------------|---------|
| **VESC** | github.com/vedderb/bldc-hardware | STM32F4 | Gate drivers, current sense, CAN | CC-BY-SA 4.0 |
| **Crazyflie** | github.com/bitcraze | STM32F4 + nRF51 | BMI088 IMU, barometer, motors | CC-BY-SA |
| **LibreSolar** | github.com/LibreSolar | STM32G4 | MPPT, BMS, CAN, current sensing | CERN OHL v2 |
| **bitaxe** | github.com/skot/bitaxe | ESP32-S3 | DCDC, ASIC, USB-C | CERN OHL |
| **ThunderScope** | github.com/EEVengers/ThunderScope | FPGA | ADC, analog frontend, PCIe | Open |

### Tier 3: Target MCU/Peripheral Designs

| Project | MCU | Key Peripherals | License |
|---------|-----|----------------|---------|
| **Cicada-GSM-HW** | STM32 | SIM7600 4G modem, production-ready | Open |
| **STM32F7 Flight Controller** | STM32F722 | ICM-42688-P IMU, BMP388 barometer | Open |
| **AtmosFC** | STM32G4 | ICM-42688-P, DPS-386, OSD | Open |
| **tokay-lite-pcb** | ESP32-S3 | OV2640 camera, TensorFlow Lite | Open |
| **nrfmicro** | nRF52840 | BLE 5, USB-C, LiPo charger | Open |
| **Feather-ZED-F9P-GPS** | N/A | u-blox ZED-F9P RTK GNSS | Open |
| **Adafruit Feather nRF52840 Sense** | nRF52840 | IMU, light, temp, humidity, mic | Open |

### Discovery Tools

| Tool | What It Does |
|------|-------------|
| **RepoRecon** (github.com/devbisme/RepoRecon) | Indexes ~40K KiCad GitHub repos, nightly JSON update |
| **Open-Schematics** (HuggingFace) | 84K `.kicad_sch` files, CC-BY-4.0 (schematics only, no PCB) |
| **OSHWA certification DB** | Searchable by hardware type and license |
| **KiCad "Made With KiCad"** | 78 curated projects across 16 categories |

### License Safety (for derivative tool-building)

**Safe:** Apache 2.0, MIT, CC-BY-4.0, CERN-OHL-P-2.0
**Caution:** CC-BY-SA-4.0, GPL-3.0, CERN-OHL-S-2.0 (copyleft may affect outputs)
**Avoid:** No license / unlicensed repos

### Data Gaps

| MCU Family | Open-Source KiCad Availability |
|------------|------------------------------|
| ESP32/S3 | Good — many community + Olimex + Adafruit designs |
| STM32F4/G4 | Good — VESC, Crazyflie, flight controllers, LibreSolar |
| Nordic nRF52840 | Limited — mostly keyboard/breakout boards, few complex products |
| NXP i.MX RT | Very sparse — most use Altium, almost nothing in KiCad |
| STM32H7 + SDRAM + display | Rare — complex H7 ref designs are Altium |

**Mitigation:** Datasheet-to-symbol pipeline makes chip availability irrelevant.
Patterns learned from ESP32/STM32 designs transfer to any chip.

---

## 6. Pipeline Architecture

### Stage 1: DISCOVER

**Input:** RepoRecon JSON (40K repos) + curated seed list
**Tool:** Python script + GitHub API
**Output:** `candidates.json`

```python
# Hard filters (instant, no API calls)
repos = [r for r in reporecon if r["stars"] >= 3]
repos = [r for r in repos if r["license"] in SAFE_LICENSES]
repos = [r for r in repos if days_since(r["pushed_at"]) < 1095]

# GitHub API: verify .kicad_sch + .kicad_pcb coexistence
# Rate limit: 30 req/min → ~500 repos in ~17 minutes

# Claude: classify README (product vs homework vs experiment)
# Cost: ~$0.50 for 500 READMEs
```

### Stage 2: ACQUIRE

**Input:** `candidates.json`
**Tool:** `git clone --depth 1` + sparse-checkout
**Output:** `data/raw/{owner}__{repo}/`

```bash
# Sparse-checkout: only KiCad files + BOMs
git sparse-checkout set --no-cone \
  '*.kicad_pro' '*.kicad_sch' '*.kicad_pcb' \
  '*.kicad_sym' '*.kicad_mod' \
  'sym-lib-table' 'fp-lib-table' \
  '*BOM*' '*bom*'
```

**Storage:** ~500MB-2GB for 100 projects (no 3D models).

### Stage 3: TRIAGE

**Input:** Raw KiCad files
**Tool:** Python regex on raw S-expression text (NOT full parse)
**Output:** `scored_projects.json`

**Complexity scoring — what actually matters:**

| Metric | How to Extract | Signal |
|--------|---------------|--------|
| Unique net count | Regex on net/label names | Best single complexity metric. Breakout=20, real board=200+ |
| Power rail count | Match `VDD\|VCC\|V3V3\|VBAT\|GND` patterns | 1-2=toy, 5+=real power tree |
| Layer count | `(layers ...)` token in .kicad_pcb | 2=hobby, 4+=serious, 6+=professional |
| Hierarchical sheet count | Count `(sheet (at` tokens | 0=flat, 3+=organized engineer |
| Max IC pin count | Parse symbols, find max pin count | 8=breakout, 48+=real MCU, 100+=SoC |
| Unique lib_id count | Distinct `(lib_id "...")` values | 5=simple, 25+=real design |
| Differential pairs | Nets matching `*_P/*_N`, `*+/*-` | USB, Ethernet, LVDS |
| Net class count | `(netclass ...)` in .kicad_pcb | 1=default, 3+=impedance-controlled |
| Has custom library | Project-local sym-lib-table with `${KIPRJMOD}` | Professionals make custom symbols |
| Has MPN | `(property "MPN" ...)` | Generic R/C=exercise, real MPNs=manufacturing |
| Component density | Count / board area from edge cuts | Space-constrained = real product |

**10 footprints is NOT a good metric.** An LED breakout with 12 resistors
passes that. Use unique net count as primary, with power rail count and
layer count as secondary signals.

### Stage 4: PARSE

**Input:** Top-scoring projects (100-200)
**Tool:** `kiutils` + custom code
**Output:** `data/parsed/{project}/project.json`

Normalized JSON schema per project:

```json
{
  "meta": {
    "project_name": "...",
    "source_url": "...",
    "license": "...",
    "kicad_version": 20231120,
    "complexity_score": 18.5
  },
  "hierarchy": {
    "root": "project.kicad_sch",
    "sheets": [
      {"name": "Power", "file": "power.kicad_sch", "parent": "root"}
    ]
  },
  "components": [
    {
      "ref": "U1",
      "lib_id": "CPU_NXP:LPC4320",
      "value": "LPC4320FBD144",
      "footprint": "LQFP-144",
      "sheet": "root",
      "mpn": "LPC4320FBD144,551",
      "pin_count": 144,
      "category": "mcu",
      "pins": {
        "1": {"name": "PF_4", "net": "SD_CMD", "type": "bidirectional"}
      }
    }
  ],
  "nets": {
    "3V3": {
      "type": "power",
      "scope": "global",
      "pins": ["U1:15", "C42:1", "C43:1"]
    }
  },
  "subcircuits": [
    {
      "center_component": "U1",
      "type": "mcu_decoupling",
      "components": ["C42", "C43", "C44"],
      "pattern": "100nF per VDD pin + 10uF bulk"
    }
  ],
  "board": {
    "layers": 4,
    "dimensions_mm": [120.5, 75.2],
    "net_classes": ["Default", "Power", "RF_50ohm"]
  }
}
```

### Stage 5: EXTRACT

**Input:** Parsed JSON for all projects
**Output:** `data/patterns/` directory

| Extraction | Method | Cost |
|------------|--------|------|
| Subcircuit detection | Graph: IC + passives within 2 net hops | $0 (code) |
| Subcircuit clustering | Fingerprint: sorted(types + topology) | $0 (code) |
| Cluster labeling | Claude: "what topology is this?" | ~$0.01/cluster |
| Component categorization | Rules + Claude for ambiguous ICs | ~$0.50 total |
| Pin functional grouping | Claude reads pin names → domains | ~$2 total |
| Decoupling rule extraction | Stats: cap values per power pin per MCU | $0 (code) |
| Placement heuristics | From .kicad_pcb: cap-to-IC distances | $0 (code) |
| Template generation | Code + Claude docstrings | ~$0.10/template |

**Total token cost for 100 projects: ~$15**

### Stage 6: VALIDATE

Three validation levels:

**Level 1 — Parse integrity (automated, free):**
```
parse .kicad_sch → JSON → regenerate .kicad_sch
kicad-cli sch export netlist original → netlist_A
kicad-cli sch export netlist regenerated → netlist_B
diff netlist_A netlist_B → MUST match
```

**Level 2 — Template correctness (automated, free):**
```
instantiate template → .kicad_sch
kicad-cli sch erc → must pass
kicad-cli sch export netlist → must be valid
check: all power pins connected, no floating inputs
```

**Level 3 — Template fidelity (automated, free):**
```
generate template from cluster of N subcircuits
instantiate template
compare netlist against each original subcircuit
target: >95% connection match
```

---

## 7. Pilot Project Set (10 Designs)

Hand-picked to cover target MCU families and peripheral types:

| # | Project | MCU | Key Peripherals | What It Teaches |
|---|---------|-----|----------------|-----------------|
| 1 | Antmicro Jetson Nano baseboard | Power ICs | USB, CSI, PCIe | Professional hierarchical design |
| 2 | MNT Reform motherboard | NXP i.MX 8M | DDR4, GbE, USB3 | SoM carrier, DDR routing |
| 3 | HackRF One | NXP LPC4320 | RF chain, SPI ADC/DAC | RF design, controlled impedance |
| 4 | VESC | STM32F4 | Gate drivers, current sense, CAN | Analog peripherals |
| 5 | Crazyflie | STM32F4 + nRF51 | BMI088 IMU, barometer, motors | IMU + BLE, dense 4-layer |
| 6 | Cicada-GSM-HW | STM32 | SIM7600 4G modem | Cellular integration |
| 7 | STM32F7 Flight Controller | STM32F722 | ICM-42688-P IMU | Flight controller pattern |
| 8 | tokay-lite-pcb | ESP32-S3 | OV2640 camera | Camera interface, AI board |
| 9 | LibreSolar MPPT-2420 | STM32G4 | DCDC, CAN, current sense | Power electronics |
| 10 | nrfmicro | nRF52840 | BLE 5, USB-C, LiPo | Nordic BLE reference |

---

## 8. Implementation Workplan

### Phase 1: Foundation (build and validate the parser)

```
TASK-001: Set up devcontainer with KiCad 9 CLI + Python deps
TASK-002: Clone 10 pilot projects to data/raw/
TASK-003: Build triage scorer (regex-based, ~100 lines)
TASK-004: Score all 10 pilots, verify rankings make sense
TASK-005: Build full parser on kiutils (schematic + PCB → JSON)
TASK-006: Parse all 10 pilots, manually inspect JSON output
TASK-007: Build netlist round-trip validator
TASK-008: Validate all 10 pilots (parse → regen → netlist diff)
TASK-009: Fix parser bugs from validation failures
TASK-010: Scale to 50+ projects, re-validate
```

### Phase 2: Pattern extraction

```
TASK-011: Build subcircuit detector (IC + connected passives graph)
TASK-012: Run subcircuit detection on all parsed projects
TASK-013: Build subcircuit fingerprinter + clusterer
TASK-014: Label clusters with Claude (Ethernet, USB, LDO, etc.)
TASK-015: Extract decoupling patterns per MCU family
TASK-016: Extract hierarchical sheet organization patterns
TASK-017: Build template generator from clusters
TASK-018: Validate templates (ERC + netlist check)
```

### Phase 3: Generation

```
TASK-019: Build datasheet PDF → structured pin data extractor
TASK-020: Build multi-unit symbol generator (.kicad_sym)
TASK-021: Build hierarchical schematic generator (.kicad_sch)
TASK-022: Build template instantiation engine
TASK-023: End-to-end test: "GPS tracker" → valid KiCad project
TASK-024: End-to-end test: novel MCU (from datasheet only) → valid project
```

### Phase 4: Manufacturing integration

```
TASK-025: Parts inventory database schema + import
TASK-026: BOM matching (design BOM → inventory → missing parts list)
TASK-027: CPL generation for LumenPNP feeder positions
TASK-028: Gerber + drill file generation pipeline
TASK-029: 3D enclosure generation (CadQuery/OpenSCAD)
```

---

## 9. Key Decisions Made

| Decision | Rationale |
|----------|-----------|
| Target KiCad 9 only | Stable S-expression format, backwards-compatible, has CLI |
| Use kiutils for parsing | Best coverage (sch + pcb), typed objects, fast, KiCad 9 tested |
| File-level parsing, not IPC API | Works headless, no KiCad instance needed, format is stable |
| RepoRecon for discovery | Already indexes 40K repos, nightly updates, don't reinvent |
| Regex triage before full parse | Score 1000 projects in minutes, only deep-parse top 200 |
| Complexity = unique nets + power rails + layers | Better than component count (breakouts have many components but few nets) |
| Apache 2.0 sources first | Cleanest license for derivative tool-building |

---

## 10. Open Questions

- [ ] Does kiutils handle all KiCad 9 edge cases? (tested on KiCad 6 + synthetic KiCad 9)
- [ ] How many of the 40K RepoRecon repos have BOTH .kicad_sch and .kicad_pcb?
- [ ] What's the actual distribution of KiCad versions across open-source projects?
- [ ] Can kicad-cli run in Docker without X11? (needed for headless validation)
- [ ] How to handle projects with custom symbols that reference global KiCad libraries?
- [ ] What's the best approach for KiCad 5 → 9 format conversion in batch?
- [ ] SKiDL vs direct S-expression generation for the output side — which is more maintainable?
