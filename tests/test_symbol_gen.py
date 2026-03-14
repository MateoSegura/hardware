"""Tests for KiCad symbol generator."""

import subprocess
import sys
import tempfile
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from kiutils.symbol import SymbolLib

from src.pipeline.symbol_gen import (
    ChipDef,
    PinDef,
    generate_symbol_file,
)


def _write_and_load(chip: ChipDef) -> tuple[Path, SymbolLib]:
    """Generate symbol file and reload it for verification."""
    tmp = Path(tempfile.mktemp(suffix=".kicad_sym"))
    generate_symbol_file(chip, tmp)
    loaded = SymbolLib.from_file(str(tmp))
    return tmp, loaded


# ---------------------------------------------------------------------------
# Test 1: Simple 4-pin symbol
# ---------------------------------------------------------------------------

def test_simple_symbol():
    """Generate a symbol with 4 pins (VCC, GND, IN, OUT), verify valid output."""
    chip = ChipDef(
        name="SimpleIC",
        library="Test",
        description="Simple test IC",
        footprint="Package_SO:SOIC-8",
        datasheet_url="https://example.com/ds.pdf",
        pins=[
            PinDef("1", "VCC", "power_in", "Power"),
            PinDef("2", "GND", "power_in", "Power"),
            PinDef("3", "IN", "input", "Signal"),
            PinDef("4", "OUT", "output", "Signal"),
        ],
    )

    path, lib = _write_and_load(chip)
    try:
        assert len(lib.symbols) == 1
        sym = lib.symbols[0]
        assert sym.entryName == "SimpleIC"

        # Should have standard properties
        prop_keys = {p.key for p in sym.properties}
        assert "Reference" in prop_keys
        assert "Value" in prop_keys
        assert "Footprint" in prop_keys
        assert "Datasheet" in prop_keys

        # Verify all 4 pins exist across all units
        all_pins = []
        for unit in sym.units:
            all_pins.extend(unit.pins)
        assert len(all_pins) == 4

        pin_names = {p.name for p in all_pins}
        assert pin_names == {"VCC", "GND", "IN", "OUT"}
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 2: Multi-unit symbol (3 groups)
# ---------------------------------------------------------------------------

def test_multi_unit_symbol():
    """Generate a symbol with 3 groups, verify 3 units created."""
    chip = ChipDef(
        name="MultiUnitIC",
        library="Test",
        description="Multi-unit test",
        footprint="QFP:LQFP-32",
        datasheet_url="",
        pins=[
            # Power group (4 pins)
            PinDef("1", "VCC", "power_in", "Power"),
            PinDef("2", "VDD", "power_in", "Power"),
            PinDef("3", "GND", "power_in", "Power"),
            PinDef("4", "VSS", "power_in", "Power"),
            # GPIO group (8 pins)
            PinDef("5", "PA0", "bidirectional", "GPIO"),
            PinDef("6", "PA1", "bidirectional", "GPIO"),
            PinDef("7", "PA2", "bidirectional", "GPIO"),
            PinDef("8", "PA3", "bidirectional", "GPIO"),
            PinDef("9", "PA4", "bidirectional", "GPIO"),
            PinDef("10", "PA5", "bidirectional", "GPIO"),
            PinDef("11", "PA6", "bidirectional", "GPIO"),
            PinDef("12", "PA7", "bidirectional", "GPIO"),
            # UART group (4 pins)
            PinDef("13", "UART_TX", "output", "UART"),
            PinDef("14", "UART_RX", "input", "UART"),
            PinDef("15", "UART_CTS", "input", "UART"),
            PinDef("16", "UART_RTS", "output", "UART"),
        ],
    )

    path, lib = _write_and_load(chip)
    try:
        sym = lib.symbols[0]
        assert len(sym.units) == 3

        # Count pins per unit
        unit_pin_counts = [len(u.pins) for u in sym.units]
        assert sorted(unit_pin_counts) == [4, 4, 8]

        # Total pins should be 16
        total_pins = sum(len(u.pins) for u in sym.units)
        assert total_pins == 16
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 3: Pin electrical types
# ---------------------------------------------------------------------------

def test_pin_types():
    """Verify power_in, bidirectional, input, output pins have correct electricalType."""
    chip = ChipDef(
        name="PinTypeIC",
        library="Test",
        description="",
        footprint="",
        datasheet_url="",
        pins=[
            PinDef("1", "VCC", "power_in", "A"),
            PinDef("2", "IO", "bidirectional", "A"),
            PinDef("3", "IN", "input", "A"),
            PinDef("4", "OUT", "output", "A"),
            PinDef("5", "PASS", "passive", "A"),
            PinDef("6", "TRI", "tri_state", "A"),
        ],
    )

    path, lib = _write_and_load(chip)
    try:
        all_pins = []
        for unit in lib.symbols[0].units:
            all_pins.extend(unit.pins)

        type_map = {p.name: p.electricalType for p in all_pins}
        assert type_map["VCC"] == "power_in"
        assert type_map["IO"] == "bidirectional"
        assert type_map["IN"] == "input"
        assert type_map["OUT"] == "output"
        assert type_map["PASS"] == "passive"
        assert type_map["TRI"] == "tri_state"
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 4: BGA pin numbers
# ---------------------------------------------------------------------------

def test_bga_pin_numbers():
    """Pin numbers like 'A4', 'C11' handled correctly."""
    chip = ChipDef(
        name="BGA_IC",
        library="Test",
        description="BGA test",
        footprint="BGA:BGA-256",
        datasheet_url="",
        pins=[
            PinDef("A1", "VCC", "power_in", "Power"),
            PinDef("A4", "PA0", "bidirectional", "GPIO"),
            PinDef("C11", "ENET_MDC", "output", "Ethernet"),
            PinDef("AB12", "DDR_DQ0", "bidirectional", "DDR"),
        ],
    )

    path, lib = _write_and_load(chip)
    try:
        all_pins = []
        for unit in lib.symbols[0].units:
            all_pins.extend(unit.pins)

        numbers = {p.number for p in all_pins}
        assert "A1" in numbers
        assert "A4" in numbers
        assert "C11" in numbers
        assert "AB12" in numbers
    finally:
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 5: kicad-cli validation
# ---------------------------------------------------------------------------

def test_kicad_cli_validates():
    """Write generated .kicad_sym, verify kicad-cli can process it."""
    chip = ChipDef(
        name="ValidatedIC",
        library="Test",
        description="Validated test IC",
        footprint="Package_SO:SOIC-8",
        datasheet_url="",
        pins=[
            PinDef("1", "VCC", "power_in", "Power"),
            PinDef("2", "GND", "power_in", "Power"),
            PinDef("3", "IN", "input", "Signal"),
            PinDef("4", "OUT", "output", "Signal"),
        ],
    )

    sym_path = Path(tempfile.mktemp(suffix=".kicad_sym"))
    svg_dir = Path(tempfile.mkdtemp(prefix="sym_svg_"))

    try:
        generate_symbol_file(chip, sym_path)

        result = subprocess.run(
            ["/usr/bin/kicad-cli", "sym", "export", "svg", str(sym_path), "-o", str(svg_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"kicad-cli failed: {result.stderr}"

        # Should have produced SVG files
        svg_files = list(svg_dir.glob("*.svg"))
        assert len(svg_files) > 0, "No SVG files produced"
    finally:
        sym_path.unlink(missing_ok=True)
        for f in svg_dir.glob("*"):
            f.unlink(missing_ok=True)
        svg_dir.rmdir()


# ---------------------------------------------------------------------------
# Test 6: STM32-like 64-pin symbol
# ---------------------------------------------------------------------------

def test_stm32_like_symbol():
    """Generate a 64-pin LQFP STM32-like symbol with multiple groups."""
    pins = []
    pin_num = 1

    # Power group (8 pins)
    for name in ["VDD1", "VDD2", "VDD3", "VDDA", "VSS1", "VSS2", "VSS3", "VSSA"]:
        pins.append(PinDef(str(pin_num), name, "power_in", "Power"))
        pin_num += 1

    # GPIO_A group (16 pins)
    for i in range(16):
        pins.append(PinDef(str(pin_num), f"PA{i}", "bidirectional", "GPIO_A"))
        pin_num += 1

    # GPIO_B group (16 pins)
    for i in range(16):
        pins.append(PinDef(str(pin_num), f"PB{i}", "bidirectional", "GPIO_B"))
        pin_num += 1

    # UART group (8 pins)
    for i in range(4):
        pins.append(PinDef(str(pin_num), f"UART{i+1}_TX", "output", "UART"))
        pin_num += 1
        pins.append(PinDef(str(pin_num), f"UART{i+1}_RX", "input", "UART"))
        pin_num += 1

    # SPI group (8 pins)
    for i in range(2):
        for sig in ["SCK", "MOSI", "MISO", "NSS"]:
            pins.append(PinDef(str(pin_num), f"SPI{i+1}_{sig}", "bidirectional", "SPI"))
            pin_num += 1

    # I2C group (8 pins)
    for i in range(4):
        pins.append(PinDef(str(pin_num), f"I2C{i+1}_SCL", "bidirectional", "I2C"))
        pin_num += 1
        pins.append(PinDef(str(pin_num), f"I2C{i+1}_SDA", "bidirectional", "I2C"))
        pin_num += 1

    assert len(pins) == 64

    chip = ChipDef(
        name="STM32F722RET6",
        library="MCU_ST",
        description="ARM Cortex-M7 MCU, 512KB Flash, 256KB RAM, LQFP-64",
        footprint="Package_QFP:LQFP-64_10x10mm_P0.5mm",
        datasheet_url="https://www.st.com/resource/en/datasheet/stm32f722re.pdf",
        pins=pins,
    )

    path, lib = _write_and_load(chip)
    try:
        sym = lib.symbols[0]

        # Should have 6 groups = 6 units
        assert len(sym.units) == 6

        # Total pins should be 64
        total_pins = sum(len(u.pins) for u in sym.units)
        assert total_pins == 64

        # Verify all pin numbers are unique
        all_pin_numbers = []
        for unit in sym.units:
            for pin in unit.pins:
                all_pin_numbers.append(pin.number)
        assert len(set(all_pin_numbers)) == 64

        # Verify properties
        prop_map = {p.key: p.value for p in sym.properties}
        assert prop_map["Value"] == "STM32F722RET6"
        assert "LQFP-64" in prop_map["Footprint"]

        # Validate with kicad-cli
        svg_dir = Path(tempfile.mkdtemp(prefix="stm32_svg_"))
        try:
            result = subprocess.run(
                ["/usr/bin/kicad-cli", "sym", "export", "svg", str(path), "-o", str(svg_dir)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, f"kicad-cli failed: {result.stderr}"
            svg_files = list(svg_dir.glob("*.svg"))
            assert len(svg_files) == 6, f"Expected 6 SVG files (one per unit), got {len(svg_files)}"
        finally:
            for f in svg_dir.glob("*"):
                f.unlink(missing_ok=True)
            svg_dir.rmdir()
    finally:
        path.unlink(missing_ok=True)
