"""Tests for the template generation module.

Uses real pattern data from data/patterns/ — no mocks.
"""

import json
from pathlib import Path

import pytest

from src.pipeline.models import CircuitTemplate, TemplatePassive
from src.pipeline.templates import (
    build_decoupling_template,
    build_template_from_cluster,
    generate_all_templates,
    save_templates,
    template_from_dict,
    template_to_dict,
)


PATTERNS_DIR = Path(__file__).resolve().parent.parent / "data" / "patterns"
CLUSTERS_PATH = PATTERNS_DIR / "subcircuit_clusters.json"
DECOUPLING_PATH = PATTERNS_DIR / "decoupling_rules.json"


@pytest.fixture
def clusters():
    with open(CLUSTERS_PATH) as f:
        return json.load(f)


@pytest.fixture
def decoupling():
    with open(DECOUPLING_PATH) as f:
        return json.load(f)


@pytest.fixture
def big_cluster(clusters):
    """A cluster with count >= 3."""
    for c in clusters["top_clusters"]:
        if c["count"] >= 3 and len(c["canonical_components"]) >= 2:
            return c
    pytest.skip("No cluster with count >= 3 and passives found")


@pytest.fixture
def big_ic_family(decoupling):
    """An IC family with sample_count >= 3 and caps."""
    for name, data in decoupling["by_ic_family"].items():
        if data["sample_count"] >= 3 and data.get("caps"):
            # Filter for families with non-empty cap values
            caps_with_values = [c for c in data["caps"] if c.get("value")]
            if caps_with_values:
                return name, data
    pytest.skip("No IC family with 3+ samples and cap values found")


# ---------------------------------------------------------------------------
# 1. Template from cluster — has center IC + passives
# ---------------------------------------------------------------------------

def test_template_from_cluster(big_cluster):
    tpl = build_template_from_cluster(big_cluster)
    assert tpl is not None
    assert isinstance(tpl, CircuitTemplate)

    # Must have a center IC
    assert tpl.center_ic_lib_id != ""

    # Must have passives (cluster has >= 2 canonical components)
    assert len(tpl.passives) > 0
    for p in tpl.passives:
        assert isinstance(p, TemplatePassive)
        assert p.ref_prefix != ""
        assert p.connection_type != ""
        assert p.count_in_template >= 1

    # Must have metadata
    assert tpl.source_count >= 3
    assert tpl.fingerprint != ""
    assert tpl.name != ""
    assert tpl.description != ""


# ---------------------------------------------------------------------------
# 2. Template passive values — most common values selected
# ---------------------------------------------------------------------------

def test_template_passive_values(big_ic_family):
    ic_family, family_data = big_ic_family
    tpl = build_decoupling_template(ic_family, family_data)
    assert tpl is not None

    # Passives should have typical values from the data
    assert len(tpl.passives) > 0
    for p in tpl.passives:
        assert p.ref_prefix == "C"
        assert p.typical_value != ""
        assert p.connection_type == "power_bypass"

    # The first passive should be the most common cap value
    caps = family_data["caps"]
    top_cap_values = [c["value"] for c in caps if c.get("value")]
    if top_cap_values:
        assert tpl.passives[0].typical_value == top_cap_values[0]


# ---------------------------------------------------------------------------
# 3. Decoupling template
# ---------------------------------------------------------------------------

def test_decoupling_template(big_ic_family):
    ic_family, family_data = big_ic_family
    tpl = build_decoupling_template(ic_family, family_data)
    assert tpl is not None

    assert tpl.name.startswith("decoupling_")
    assert tpl.center_ic_lib_id == ic_family
    assert tpl.source_count == family_data["sample_count"]
    assert tpl.fingerprint == f"decoupling_{ic_family}"
    assert len(tpl.passives) > 0

    # All passives should be capacitors
    for p in tpl.passives:
        assert p.ref_prefix == "C"


# ---------------------------------------------------------------------------
# 4. Min cluster size — clusters with <3 instances should NOT generate
# ---------------------------------------------------------------------------

def test_min_cluster_size():
    small_cluster = {
        "fingerprint": "abc123",
        "count": 2,
        "label": "",
        "canonical_components": ["Package:QFP-48", "C", "R"],
        "example_projects": ["U1", "U2"],
    }
    tpl = build_template_from_cluster(small_cluster)
    assert tpl is None

    # Also test with count=1
    small_cluster["count"] = 1
    tpl = build_template_from_cluster(small_cluster)
    assert tpl is None

    # Edge: count=0
    small_cluster["count"] = 0
    tpl = build_template_from_cluster(small_cluster)
    assert tpl is None


def test_min_cluster_size_decoupling():
    small_family = {
        "sample_count": 2,
        "caps": [{"value": "100nF", "footprint": "C_0402", "count": 5}],
        "power_nets": ["VCC", "GND"],
    }
    tpl = build_decoupling_template("SmallIC", small_family)
    assert tpl is None


# ---------------------------------------------------------------------------
# 5. Template serialization — JSON roundtrip
# ---------------------------------------------------------------------------

def test_template_serialization():
    tpl = CircuitTemplate(
        name="test_ldo_bypass",
        description="Test LDO with bypass caps",
        center_ic_lib_id="Regulator_Linear:MCP1700-3302E",
        center_ic_footprint="Package_TO_SOT_SMD:SOT-23",
        passives=[
            TemplatePassive(
                ref_prefix="C",
                typical_value="1uF",
                typical_footprint="C_0402",
                connection_type="power_bypass",
                count_in_template=2,
            ),
            TemplatePassive(
                ref_prefix="R",
                typical_value="10k",
                typical_footprint="R_0402",
                connection_type="pullup",
                count_in_template=1,
            ),
        ],
        source_count=5,
        source_projects=["proj_a", "proj_b", "proj_c"],
        fingerprint="deadbeef12345678",
    )

    # Serialize to dict
    d = template_to_dict(tpl)
    assert isinstance(d, dict)
    assert d["name"] == "test_ldo_bypass"
    assert len(d["passives"]) == 2

    # JSON roundtrip
    json_str = json.dumps(d)
    d2 = json.loads(json_str)
    tpl2 = template_from_dict(d2)

    assert tpl2.name == tpl.name
    assert tpl2.description == tpl.description
    assert tpl2.center_ic_lib_id == tpl.center_ic_lib_id
    assert tpl2.center_ic_footprint == tpl.center_ic_footprint
    assert tpl2.source_count == tpl.source_count
    assert tpl2.fingerprint == tpl.fingerprint
    assert len(tpl2.passives) == len(tpl.passives)
    assert tpl2.passives[0].typical_value == "1uF"
    assert tpl2.passives[1].ref_prefix == "R"
    assert tpl2.source_projects == ["proj_a", "proj_b", "proj_c"]


# ---------------------------------------------------------------------------
# 6. Generate all templates — at least 5 from real data
# ---------------------------------------------------------------------------

def test_generate_all_templates():
    templates = generate_all_templates(
        clusters_path=CLUSTERS_PATH,
        decoupling_path=DECOUPLING_PATH,
    )
    assert len(templates) >= 5

    # All should be CircuitTemplate instances
    for tpl in templates:
        assert isinstance(tpl, CircuitTemplate)
        assert tpl.name != ""
        assert tpl.source_count >= 3
        assert tpl.fingerprint != ""

    # Should have both cluster-based and decoupling-based templates
    cluster_templates = [t for t in templates if not t.fingerprint.startswith("decoupling_")]
    decoupling_templates = [t for t in templates if t.fingerprint.startswith("decoupling_")]
    assert len(cluster_templates) > 0, "Expected cluster-based templates"
    assert len(decoupling_templates) > 0, "Expected decoupling templates"


# ---------------------------------------------------------------------------
# Additional: save templates
# ---------------------------------------------------------------------------

def test_save_templates(tmp_path):
    templates = [
        CircuitTemplate(
            name="test_save",
            description="test",
            center_ic_lib_id="Device:Test",
            center_ic_footprint="SOT-23",
            passives=[
                TemplatePassive("C", "100nF", "C_0402", "power_bypass", 1),
            ],
            source_count=5,
            source_projects=["a", "b"],
            fingerprint="abc123",
        ),
    ]

    out_dir = save_templates(templates, output_dir=tmp_path / "templates")

    # Check summary file
    summary_path = out_dir / "templates_summary.json"
    assert summary_path.is_file()
    with open(summary_path) as f:
        summary = json.load(f)
    assert len(summary) == 1
    assert summary[0]["name"] == "test_save"

    # Check individual template file
    tpl_path = out_dir / "test_save.json"
    assert tpl_path.is_file()
    with open(tpl_path) as f:
        tpl_data = json.load(f)
    assert tpl_data["center_ic_lib_id"] == "Device:Test"
    assert len(tpl_data["passives"]) == 1
