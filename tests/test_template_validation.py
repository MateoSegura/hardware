"""Tests for template ERC validation.

Verifies that circuit templates can be instantiated into KiCad schematics
and validated with kicad-cli ERC without crashing.
"""

import json
from pathlib import Path


from src.pipeline.models import CircuitTemplate, TemplatePassive
from src.pipeline.schematic_gen import generate_schematic
from src.pipeline.templates import generate_all_templates

# Import from the validation script
import sys
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from validate_templates import (
    instantiate_template,
    validate_template,
    validate_all_templates,
)


def _make_decoupling_template(name: str = "test_decoupling") -> CircuitTemplate:
    """Create a minimal decoupling template for testing."""
    return CircuitTemplate(
        name=name,
        description=f"Test decoupling template: {name}",
        center_ic_lib_id="Device:C",
        center_ic_footprint="Capacitor_SMD:C_0402_1005Metric",
        passives=[
            TemplatePassive(
                ref_prefix="C",
                typical_value="100nF",
                typical_footprint="Capacitor_SMD:C_0402_1005Metric",
                connection_type="power_bypass",
                count_in_template=2,
            ),
        ],
        source_count=10,
        source_projects=["test_project"],
        fingerprint="test_fingerprint",
    )


class TestValidateSingleTemplate:
    """Test: instantiate one decoupling template, run ERC, verify no crash."""

    def test_instantiate_produces_components(self):
        """Instantiation produces ComponentPlacement and NetConnection objects."""
        tpl = _make_decoupling_template()
        components, nets = instantiate_template(tpl)

        # Should have center IC + 2 caps
        assert len(components) == 3
        assert components[0].ref == "U1"
        assert components[1].ref == "C1"
        assert components[2].ref == "C2"

        # Should have VCC and GND net labels
        assert len(nets) == 2
        net_names = {n.net_name for n in nets}
        assert "VCC" in net_names
        assert "GND" in net_names

    def test_generate_schematic_valid(self):
        """Generated schematic content is non-empty and looks like KiCad format."""
        tpl = _make_decoupling_template()
        components, nets = instantiate_template(tpl)
        sch_content = generate_schematic(
            components=components,
            nets=nets,
            title="Test_Template",
        )
        assert sch_content.startswith("(kicad_sch")
        assert "Device:C" in sch_content
        assert '"C1"' in sch_content
        assert '"VCC"' in sch_content

    def test_validate_single_template_erc_runs(self):
        """ERC runs on a single decoupling template without crashing."""
        tpl = _make_decoupling_template()
        result = validate_template(tpl)

        assert result["name"] == "test_decoupling"
        assert result["passive_count"] == 1
        # ERC must have run successfully (kicad-cli executed without crash)
        assert result["erc_success"] is True
        # violations/errors/warnings are integers
        assert isinstance(result["erc_violations"], int)
        assert isinstance(result["erc_errors"], int)
        assert isinstance(result["erc_warnings"], int)


class TestValidateBatch:
    """Test: validate multiple templates, verify all produce ERC results."""

    def _get_templates_with_passives(self, count: int) -> list[CircuitTemplate]:
        """Get up to `count` templates that have passives.

        Tries real data first, falls back to synthetic templates.
        """
        templates = generate_all_templates()
        with_passives = [t for t in templates if t.passives]

        if len(with_passives) >= count:
            return with_passives[:count]

        # Supplement with synthetic templates if needed
        while len(with_passives) < count:
            idx = len(with_passives) + 1
            with_passives.append(_make_decoupling_template(f"synthetic_{idx}"))
        return with_passives[:count]

    def test_validate_batch_five_templates(self):
        """Validate 5 templates, verify all produce ERC results."""
        templates = self._get_templates_with_passives(5)
        assert len(templates) == 5

        results = validate_all_templates(templates)
        assert len(results) == 5

        for result in results:
            # Every result must have the expected keys
            assert "name" in result
            assert "erc_success" in result
            assert "erc_violations" in result
            assert "erc_errors" in result
            assert "erc_warnings" in result
            # ERC must have executed (success=True means kicad-cli ran)
            assert result["erc_success"] is True, (
                f"ERC failed for {result['name']}: {result['erc_stderr']}"
            )

    def test_validate_batch_results_are_serializable(self):
        """Validation results can be serialized to JSON for the report."""
        templates = self._get_templates_with_passives(3)
        results = validate_all_templates(templates)

        # Should be JSON-serializable
        json_str = json.dumps(results, indent=2)
        parsed = json.loads(json_str)
        assert len(parsed) == 3
        assert all("name" in r for r in parsed)
