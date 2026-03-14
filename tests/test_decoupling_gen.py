"""Tests for decoupling capacitor auto-generation (decoupled from templates).

TDD — tests written first, then implementation.
"""

import json
import math
import subprocess
import tempfile
from pathlib import Path


from src.pipeline.schematic_gen import (
    generate_schematic,
)
from src.pipeline.decoupling_gen import (
    generate_decoupling_caps,
    generate_decoupling_nets,
)

RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "patterns" / "decoupling_rules.json"


# ---------------------------------------------------------------------------
# Test 1: Known IC family should produce caps matching decoupling_rules.json
# ---------------------------------------------------------------------------

def test_generate_caps_known_family():
    """STM32F7 family should generate caps matching decoupling_rules.json."""
    caps = generate_decoupling_caps(
        ic_lib_id="MCU_ST:STM32F722RET6",
        ic_position=(100.0, 80.0),
        power_nets=["+3.3V", "+3.3VA"],
        ground_net="GND",
        rules_path=RULES_PATH,
    )

    assert len(caps) > 0, "Should generate at least one decoupling cap"

    # Load rules to verify values match
    with open(RULES_PATH) as f:
        rules = json.load(f)
    family_data = rules["by_ic_family"]["STM32F7"]
    rule_values = {c["value"] for c in family_data["caps"]}

    # Every cap value should come from the rules
    for cap in caps:
        assert cap.lib_id == "Device:C"
        assert cap.value in rule_values, f"Cap value {cap.value} not in STM32F7 rules"


# ---------------------------------------------------------------------------
# Test 2: Unknown IC family should use defaults
# ---------------------------------------------------------------------------

def test_generate_caps_unknown_family():
    """Unknown IC should use defaults: 100nF per power net + 10uF bulk."""
    caps = generate_decoupling_caps(
        ic_lib_id="Custom:XYZABC123",
        ic_position=(100.0, 80.0),
        power_nets=["+3.3V", "+5V"],
        ground_net="GND",
        rules_path=RULES_PATH,
    )

    assert len(caps) > 0, "Should generate default caps for unknown IC"

    values = [c.value for c in caps]
    # Should have 100nF per power net
    assert values.count("100nF") >= 2, "Should have at least one 100nF per power net"
    # Should have at least one 10uF bulk cap
    assert "10uF" in values, "Should have a 10uF bulk cap"

    # Check footprints match defaults
    for cap in caps:
        if cap.value == "100nF":
            assert cap.footprint == "Capacitor_SMD:C_0402_1005Metric"
        elif cap.value == "10uF":
            assert cap.footprint == "Capacitor_SMD:C_0805_2012Metric"


# ---------------------------------------------------------------------------
# Test 3: All cap refs should be unique
# ---------------------------------------------------------------------------

def test_cap_refs_unique():
    """All generated caps should have unique reference designators."""
    caps = generate_decoupling_caps(
        ic_lib_id="MCU_ST:STM32F722RET6",
        ic_position=(100.0, 80.0),
        power_nets=["+3.3V", "+3.3VA", "+BATT"],
        ground_net="GND",
        rules_path=RULES_PATH,
    )

    refs = [c.ref for c in caps]
    assert len(refs) == len(set(refs)), f"Duplicate refs found: {refs}"

    # All refs should start with "C" followed by a number
    for ref in refs:
        assert ref.startswith("C"), f"Cap ref should start with C: {ref}"
        assert ref[1:].isdigit(), f"Cap ref suffix should be numeric: {ref}"


# ---------------------------------------------------------------------------
# Test 4: Caps positioned near the IC
# ---------------------------------------------------------------------------

def test_caps_positioned_near_ic():
    """All caps should be within 30mm (30 schematic units) of the IC position."""
    ic_pos = (120.0, 90.0)
    caps = generate_decoupling_caps(
        ic_lib_id="MCU_ST:STM32F722RET6",
        ic_position=ic_pos,
        power_nets=["+3.3V"],
        ground_net="GND",
        rules_path=RULES_PATH,
    )

    for cap in caps:
        dx = cap.position[0] - ic_pos[0]
        dy = cap.position[1] - ic_pos[1]
        distance = math.sqrt(dx * dx + dy * dy)
        assert distance <= 30.0, (
            f"Cap {cap.ref} at {cap.position} is {distance:.1f} units from IC at {ic_pos}"
        )


# ---------------------------------------------------------------------------
# Test 5: Power and ground net connections
# ---------------------------------------------------------------------------

def test_power_net_connections():
    """Generated nets should include both power and ground connections."""
    power_nets = ["+3.3V", "+5V"]
    ground_net = "GND"

    caps = generate_decoupling_caps(
        ic_lib_id="Custom:XYZABC123",
        ic_position=(100.0, 80.0),
        power_nets=power_nets,
        ground_net=ground_net,
        rules_path=RULES_PATH,
    )

    nets = generate_decoupling_nets(caps, power_nets, ground_net)

    assert len(nets) > 0, "Should generate net connections"

    net_names = {n.net_name for n in nets}
    # Should have ground connections
    assert ground_net in net_names, "Should have GND net connections"
    # Should have at least one power net connection
    assert any(pn in net_names for pn in power_nets), "Should have power net connections"

    # All nets should be global labels (power nets are global)
    for net in nets:
        assert net.label_type in ("global", "power"), (
            f"Net {net.net_name} should be global or power, got {net.label_type}"
        )


# ---------------------------------------------------------------------------
# Test 6: Integration with schematic generator
# ---------------------------------------------------------------------------

def test_integration_with_schematic_gen():
    """Generate caps then feed to generate_schematic() — should produce valid output."""
    ic_pos = (100.0, 80.0)
    power_nets = ["+3.3V"]

    caps = generate_decoupling_caps(
        ic_lib_id="MCU_ST:STM32F722RET6",
        ic_position=ic_pos,
        power_nets=power_nets,
        ground_net="GND",
        rules_path=RULES_PATH,
    )
    nets = generate_decoupling_nets(caps, power_nets, "GND")

    content = generate_schematic(caps, nets, title="Decoupling_Test")

    # Valid KiCad schematic structure
    assert content.startswith("(kicad_sch")
    assert content.strip().endswith(")")
    assert '(version 20250114)' in content
    assert '"Device:C"' in content

    # All cap refs present
    for cap in caps:
        assert f'"{cap.ref}"' in content
    # Net labels present
    for net in nets:
        assert f'"{net.net_name}"' in content


# ---------------------------------------------------------------------------
# Test 7: KiCad CLI ERC validation
# ---------------------------------------------------------------------------

def test_integration_kicad_validates():
    """Generate caps + schematic, run kicad-cli ERC — should not crash."""
    ic_pos = (100.0, 80.0)
    power_nets = ["+3.3V"]

    caps = generate_decoupling_caps(
        ic_lib_id="Custom:UNKNOWN_IC",
        ic_position=ic_pos,
        power_nets=power_nets,
        ground_net="GND",
        rules_path=RULES_PATH,
    )
    nets = generate_decoupling_nets(caps, power_nets, "GND")

    content = generate_schematic(caps, nets, title="Decoupling_ERC_Test")

    with tempfile.TemporaryDirectory() as tmpdir:
        sch_path = Path(tmpdir) / "decoupling_erc_test.kicad_sch"
        sch_path.write_text(content)

        # kicad-cli erc should run without crashing (exit 0 or ERC violations are ok)
        result = subprocess.run(
            ["kicad-cli", "sch", "erc", str(sch_path), "--severity-error"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # kicad-cli returns 0 on success or ERC violations — we just care it doesn't crash
        assert result.returncode in (0, 1, 5), (
            f"kicad-cli crashed with return code {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
