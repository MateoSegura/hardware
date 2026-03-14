"""Tests for KiCad schematic generator."""

import re
import subprocess
import tempfile
from pathlib import Path


from src.pipeline.schematic_gen import (
    ComponentPlacement,
    NetConnection,
    SheetContent,
    generate_hierarchical_project,
    generate_schematic,
)


# ---------------------------------------------------------------------------
# Test 1: Simple schematic with 2 resistors and a label
# ---------------------------------------------------------------------------

def test_generate_simple_schematic():
    """Generate schematic with 2 resistors and a label, verify valid S-expression."""
    components = [
        ComponentPlacement(
            lib_id="Device:R",
            ref="R1",
            value="10k",
            footprint="Resistor_SMD:R_0402_1005Metric",
            position=(100.0, 60.0),
        ),
        ComponentPlacement(
            lib_id="Device:R",
            ref="R2",
            value="4.7k",
            footprint="Resistor_SMD:R_0402_1005Metric",
            position=(100.0, 80.0),
        ),
    ]
    nets = [
        NetConnection(net_name="SIG_OUT", label_type="local", position=(110.0, 60.0)),
    ]

    content = generate_schematic(components, nets, title="Simple Test")

    # Valid S-expression structure
    assert content.startswith("(kicad_sch")
    assert content.strip().endswith(")")

    # Header fields
    assert '(version 20250114)' in content
    assert '(generator "hardware-pipeline")' in content
    assert '(paper "A4")' in content

    # lib_symbols section present with Device:R
    assert '(lib_symbols' in content
    assert '"Device:R"' in content

    # Components placed
    assert '"R1"' in content
    assert '"R2"' in content
    assert '"10k"' in content
    assert '"4.7k"' in content
    assert 'Resistor_SMD:R_0402_1005Metric' in content

    # Net label placed
    assert '"SIG_OUT"' in content
    assert '(label "SIG_OUT"' in content

    # sheet_instances present
    assert '(sheet_instances' in content


# ---------------------------------------------------------------------------
# Test 2: Power labels (VCC/GND)
# ---------------------------------------------------------------------------

def test_generate_with_power_labels():
    """Generate schematic with VCC/GND power labels."""
    components = [
        ComponentPlacement(
            lib_id="Device:C",
            ref="C1",
            value="100nF",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            position=(120.0, 70.0),
        ),
    ]
    nets = [
        NetConnection(net_name="VCC", label_type="power", position=(120.0, 60.0)),
        NetConnection(net_name="GND", label_type="power", position=(120.0, 80.0)),
        NetConnection(net_name="SPI_CLK", label_type="global", position=(130.0, 70.0)),
    ]

    content = generate_schematic(components, nets, title="Power Test")

    # Power labels
    assert '(power_port "VCC"' in content
    assert '(power_port "GND"' in content

    # Global label
    assert '(global_label "SPI_CLK"' in content

    # Component
    assert '"Device:C"' in content
    assert '"C1"' in content
    assert '"100nF"' in content


# ---------------------------------------------------------------------------
# Test 3: kicad-cli validation
# ---------------------------------------------------------------------------

def test_kicad_cli_validates():
    """Write generated .kicad_sch, run kicad-cli sch erc — should not crash."""
    components = [
        ComponentPlacement(
            lib_id="Device:R",
            ref="R1",
            value="10k",
            footprint="Resistor_SMD:R_0402_1005Metric",
            position=(100.0, 60.0),
        ),
        ComponentPlacement(
            lib_id="Device:C",
            ref="C1",
            value="100nF",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            position=(100.0, 80.0),
        ),
    ]
    nets = [
        NetConnection(net_name="NET1", label_type="local", position=(110.0, 60.0)),
    ]

    content = generate_schematic(components, nets, title="Validated")

    sch_path = Path(tempfile.mktemp(suffix=".kicad_sch"))
    try:
        sch_path.write_text(content)

        # Run kicad-cli — we just need it to parse without crashing
        # ERC violations are fine, crashes mean invalid file format
        result = subprocess.run(
            ["/usr/bin/kicad-cli", "sch", "erc", str(sch_path),
             "--format", "json", "-o", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # returncode 0 = clean, non-zero but no crash = ERC violations (OK)
        # A truly invalid file causes kicad-cli to crash or output errors about parsing
        assert "Error" not in result.stderr or "ERC" in result.stderr, (
            f"kicad-cli parse error: {result.stderr}"
        )
    finally:
        sch_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 4: Hierarchical project
# ---------------------------------------------------------------------------

def test_hierarchical_project():
    """Generate root + 2 sub-sheets with hierarchical labels."""
    sheets = {
        "power.kicad_sch": SheetContent(
            title="Power",
            components=[
                ComponentPlacement(
                    lib_id="Device:C",
                    ref="C1",
                    value="100nF",
                    footprint="Capacitor_SMD:C_0402_1005Metric",
                    position=(100.0, 60.0),
                ),
            ],
            nets=[
                NetConnection(net_name="VCC_3V3", label_type="global", position=(100.0, 50.0)),
            ],
            hierarchical_labels=[
                ("VCC_OUT", "output"),
                ("GND", "passive"),
            ],
        ),
        "mcu.kicad_sch": SheetContent(
            title="MCU",
            components=[
                ComponentPlacement(
                    lib_id="Device:R",
                    ref="R1",
                    value="10k",
                    footprint="Resistor_SMD:R_0402_1005Metric",
                    position=(120.0, 60.0),
                ),
            ],
            nets=[],
            hierarchical_labels=[
                ("VCC_IN", "input"),
                ("SPI_MOSI", "output"),
            ],
        ),
    }

    result = generate_hierarchical_project(sheets, root_title="TestProject")

    # Should have root + 2 sub-sheets = 3 files
    assert len(result) == 3

    # Root file exists
    assert "testproject.kicad_sch" in result
    root = result["testproject.kicad_sch"]

    # Root contains sheet references
    assert '(sheet' in root
    assert '"Power"' in root
    assert '"MCU"' in root
    assert '"power.kicad_sch"' in root
    assert '"mcu.kicad_sch"' in root

    # Sub-sheets exist and have content
    assert "power.kicad_sch" in result
    power = result["power.kicad_sch"]
    assert '(kicad_sch' in power
    assert '"C1"' in power
    assert '(hierarchical_label "VCC_OUT"' in power
    assert '(hierarchical_label "GND"' in power

    assert "mcu.kicad_sch" in result
    mcu = result["mcu.kicad_sch"]
    assert '(kicad_sch' in mcu
    assert '"R1"' in mcu
    assert '(hierarchical_label "VCC_IN"' in mcu
    assert '(hierarchical_label "SPI_MOSI"' in mcu


# ---------------------------------------------------------------------------
# Test 5: Hierarchical project kicad-cli validation
# ---------------------------------------------------------------------------

def test_hierarchical_kicad_validates():
    """Write hierarchical project, run kicad-cli on root — should not crash."""
    sheets = {
        "power.kicad_sch": SheetContent(
            title="Power",
            components=[
                ComponentPlacement(
                    lib_id="Device:R",
                    ref="R1",
                    value="10k",
                    footprint="Resistor_SMD:R_0402_1005Metric",
                    position=(100.0, 60.0),
                ),
            ],
            nets=[],
            hierarchical_labels=[("VCC", "output")],
        ),
    }

    result = generate_hierarchical_project(sheets, root_title="HierTest")

    tmp_dir = Path(tempfile.mkdtemp(prefix="hier_test_"))
    try:
        # Write all files
        for filename, content in result.items():
            (tmp_dir / filename).write_text(content)

        # Find root file
        root_file = tmp_dir / "hiertest.kicad_sch"
        assert root_file.exists()

        # Run kicad-cli on root
        result_proc = subprocess.run(
            ["/usr/bin/kicad-cli", "sch", "erc", str(root_file),
             "--format", "json", "-o", "/dev/null"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should not crash — ERC violations are acceptable
        # kicad-cli exits 0 even with ERC violations when format=json
        # A malformed file would cause a parse error in stderr
        assert "Unable to load" not in result_proc.stderr, (
            f"kicad-cli could not load file: {result_proc.stderr}"
        )
    finally:
        for f in tmp_dir.glob("*"):
            f.unlink(missing_ok=True)
        tmp_dir.rmdir()


# ---------------------------------------------------------------------------
# Test 6: UUID uniqueness
# ---------------------------------------------------------------------------

def test_component_uuids_unique():
    """Verify all UUIDs in generated output are unique."""
    components = [
        ComponentPlacement(
            lib_id="Device:R", ref=f"R{i}", value="10k",
            footprint="Resistor_SMD:R_0402_1005Metric",
            position=(100.0, 40.0 + i * 20.0),
        )
        for i in range(1, 11)
    ]
    nets = [
        NetConnection(net_name=f"NET{i}", label_type="local",
                      position=(120.0, 40.0 + i * 20.0))
        for i in range(1, 6)
    ]

    content = generate_schematic(components, nets, title="UUID Test")

    # Extract UUIDs from (uuid "...") declarations only — not path references
    uuid_pattern = re.compile(
        r'\(uuid "([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"\)'
    )
    all_uuids = uuid_pattern.findall(content)

    # Should have many UUIDs (root + components + pins + labels)
    assert len(all_uuids) >= 10 + 5 + 1  # at least components + labels + root

    # All declared UUIDs should be unique
    assert len(all_uuids) == len(set(all_uuids)), (
        f"Found {len(all_uuids) - len(set(all_uuids))} duplicate UUIDs"
    )
