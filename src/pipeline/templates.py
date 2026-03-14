"""Template generation from subcircuit clusters and decoupling rules.

Takes the top subcircuit clusters (from pattern extraction) and builds
reusable circuit templates capturing the center IC, supporting passives,
typical values, and provenance metadata.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from .models import CircuitTemplate, TemplatePassive

logger = logging.getLogger(__name__)

# Default data paths (relative to repo root)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PATTERNS_DIR = _REPO_ROOT / "data" / "patterns"
_PARSED_DIR = _REPO_ROOT / "data" / "parsed"
_TEMPLATES_DIR = _PATTERNS_DIR / "templates"

# Minimum number of instances to generate a template
MIN_CLUSTER_SIZE = 3

# Reference prefix -> connection type heuristics
_CONNECTION_TYPE_MAP = {
    "C": "power_bypass",
    "R": "pullup",
    "L": "inductor_filter",
    "FB": "ferrite_bead",
    "D": "protection_diode",
    "RN": "resistor_network",
    "F": "fuse",
    "JP": "jumper",
    "J": "connector",
    "DA": "diode_array",
    "RA": "resistor_array",
}


def _ref_prefix(ref: str) -> str:
    """Extract the alphabetic prefix from a reference designator."""
    match = re.match(r"^([A-Za-z]+)", ref)
    return match.group(1) if match else ref


def _most_common(items: list[str], default: str = "") -> str:
    """Return the most common non-empty item."""
    filtered = [i for i in items if i]
    if not filtered:
        return default
    counter = Counter(filtered)
    return counter.most_common(1)[0][0]


def _connection_type_for_prefix(prefix: str) -> str:
    """Map a reference prefix to a connection type."""
    return _CONNECTION_TYPE_MAP.get(prefix, "supporting")


def _sanitize_name(text: str) -> str:
    """Create a filesystem-safe name from arbitrary text."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", text)
    return re.sub(r"_+", "_", safe).strip("_")[:80]


def _load_parsed_components(project_name: str) -> list[dict]:
    """Load all components from a parsed project directory."""
    project_dir = _PARSED_DIR / project_name
    if not project_dir.is_dir():
        return []

    all_comps = []
    project_json = project_dir / "project.json"
    if project_json.is_file():
        try:
            with open(project_json) as f:
                data = json.load(f)
            # project.json can be a list of design units or a single dict
            units = data if isinstance(data, list) else [data]
            for unit in units:
                all_comps.extend(unit.get("all_components", []))
        except (json.JSONDecodeError, KeyError):
            pass
    else:
        # Fall back to individual JSON files
        for jf in sorted(project_dir.glob("*.json")):
            try:
                with open(jf) as f:
                    data = json.load(f)
                if isinstance(data, dict) and "all_components" in data:
                    all_comps.extend(data["all_components"])
            except (json.JSONDecodeError, KeyError):
                pass

    return all_comps


def build_template_from_cluster(
    cluster: dict,
    parsed_dir: Path | None = None,
) -> CircuitTemplate | None:
    """Build a CircuitTemplate from a subcircuit cluster.

    Args:
        cluster: A cluster dict from subcircuit_clusters.json with keys:
            fingerprint, count, label, canonical_components, example_projects
        parsed_dir: Override for parsed data directory.

    Returns:
        A CircuitTemplate if the cluster has enough data, else None.
    """
    count = cluster.get("count", 0)
    if count < MIN_CLUSTER_SIZE:
        return None

    fingerprint = cluster.get("fingerprint", "")
    canonical = cluster.get("canonical_components", [])
    examples = cluster.get("example_projects", [])
    label = cluster.get("label", "")

    if not canonical:
        return None

    # The first canonical component is typically the center IC (footprint/lib_id)
    center_ic_fp = canonical[0] if canonical else ""
    passive_prefixes = canonical[1:] if len(canonical) > 1 else []

    # Count how many of each passive prefix appear
    prefix_counts = Counter(passive_prefixes)

    # Build passive list
    passives = []
    for prefix, cnt in sorted(prefix_counts.items()):
        passives.append(TemplatePassive(
            ref_prefix=prefix,
            typical_value="",
            typical_footprint="",
            connection_type=_connection_type_for_prefix(prefix),
            count_in_template=cnt,
        ))

    # Generate name
    if label:
        name = _sanitize_name(label)
    else:
        fp_short = center_ic_fp.split(":")[-1] if ":" in center_ic_fp else center_ic_fp
        passive_str = "_".join(sorted(prefix_counts.keys()))
        name = _sanitize_name(f"{fp_short}_{passive_str}") if passive_str else _sanitize_name(fp_short)

    description = f"Circuit template: {center_ic_fp} with {', '.join(passive_prefixes)}" if passive_prefixes else f"Circuit template: {center_ic_fp}"

    return CircuitTemplate(
        name=name,
        description=description,
        center_ic_lib_id=center_ic_fp,
        center_ic_footprint=center_ic_fp,
        passives=passives,
        source_count=count,
        source_projects=examples,
        fingerprint=fingerprint,
    )


def build_decoupling_template(
    ic_family: str,
    family_data: dict,
) -> CircuitTemplate | None:
    """Build a decoupling template from IC family data.

    Args:
        ic_family: IC family name (e.g., "STM32F4")
        family_data: Dict with keys: sample_count, caps, power_nets

    Returns:
        A CircuitTemplate for the decoupling pattern, or None.
    """
    sample_count = family_data.get("sample_count", 0)
    if sample_count < MIN_CLUSTER_SIZE:
        return None

    caps = family_data.get("caps", [])
    if not caps:
        return None

    # Build passives from the most common cap values
    passives = []
    for cap in caps[:5]:  # Top 5 cap values
        value = cap.get("value", "")
        footprint = cap.get("footprint", "")
        cap_count = cap.get("count", 1)

        if not value:
            continue

        passives.append(TemplatePassive(
            ref_prefix="C",
            typical_value=value,
            typical_footprint=footprint,
            connection_type="power_bypass",
            count_in_template=cap_count,
        ))

    if not passives:
        return None

    power_nets = family_data.get("power_nets", [])
    power_str = ", ".join(power_nets[:3]) if power_nets else "VCC/GND"

    name = _sanitize_name(f"decoupling_{ic_family}")
    description = f"Decoupling pattern for {ic_family} ({power_str}), from {sample_count} samples"

    return CircuitTemplate(
        name=name,
        description=description,
        center_ic_lib_id=ic_family,
        center_ic_footprint="",
        passives=passives,
        source_count=sample_count,
        source_projects=[],
        fingerprint=f"decoupling_{ic_family}",
    )


def generate_all_templates(
    clusters_path: Path | None = None,
    decoupling_path: Path | None = None,
    min_cluster_size: int = MIN_CLUSTER_SIZE,
) -> list[CircuitTemplate]:
    """Generate all templates from cluster and decoupling data.

    Args:
        clusters_path: Path to subcircuit_clusters.json.
        decoupling_path: Path to decoupling_rules.json.
        min_cluster_size: Minimum instances to generate a template.

    Returns:
        List of CircuitTemplate objects.
    """
    if clusters_path is None:
        clusters_path = _PATTERNS_DIR / "subcircuit_clusters.json"
    if decoupling_path is None:
        decoupling_path = _PATTERNS_DIR / "decoupling_rules.json"

    templates: list[CircuitTemplate] = []

    # Phase 1: Templates from subcircuit clusters
    if clusters_path.is_file():
        try:
            with open(clusters_path) as f:
                data = json.load(f)
            clusters = data.get("top_clusters", [])
            for cluster in clusters:
                if cluster.get("count", 0) < min_cluster_size:
                    continue
                tpl = build_template_from_cluster(cluster)
                if tpl is not None:
                    templates.append(tpl)
            logger.info("Generated %d templates from %d clusters", len(templates), len(clusters))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load clusters: %s", e)

    # Phase 2: Templates from decoupling rules
    decoupling_count = 0
    if decoupling_path.is_file():
        try:
            with open(decoupling_path) as f:
                data = json.load(f)
            families = data.get("by_ic_family", {})
            for ic_family, family_data in families.items():
                if family_data.get("sample_count", 0) < min_cluster_size:
                    continue
                tpl = build_decoupling_template(ic_family, family_data)
                if tpl is not None:
                    templates.append(tpl)
                    decoupling_count += 1
            logger.info("Generated %d decoupling templates from %d families", decoupling_count, len(families))
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Failed to load decoupling rules: %s", e)

    return templates


def save_templates(
    templates: list[CircuitTemplate],
    output_dir: Path | None = None,
) -> Path:
    """Save templates to JSON files.

    Creates:
      - templates_summary.json: list of all templates with metadata
      - One JSON file per template with full details

    Returns:
        The output directory path.
    """
    if output_dir is None:
        output_dir = _TEMPLATES_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Summary
    summary = []
    for tpl in templates:
        summary.append({
            "name": tpl.name,
            "description": tpl.description,
            "center_ic_lib_id": tpl.center_ic_lib_id,
            "source_count": tpl.source_count,
            "passive_count": len(tpl.passives),
            "fingerprint": tpl.fingerprint,
        })

    summary_path = output_dir / "templates_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Individual template files
    for tpl in templates:
        filename = f"{tpl.name}.json"
        filepath = output_dir / filename
        with open(filepath, "w") as f:
            json.dump(asdict(tpl), f, indent=2)

    logger.info("Saved %d templates to %s", len(templates), output_dir)
    return output_dir


def template_to_dict(tpl: CircuitTemplate) -> dict:
    """Serialize a CircuitTemplate to a JSON-safe dict."""
    return asdict(tpl)


def template_from_dict(d: dict) -> CircuitTemplate:
    """Deserialize a CircuitTemplate from a dict."""
    passives = [TemplatePassive(**p) for p in d.get("passives", [])]
    return CircuitTemplate(
        name=d["name"],
        description=d.get("description", ""),
        center_ic_lib_id=d.get("center_ic_lib_id", ""),
        center_ic_footprint=d.get("center_ic_footprint", ""),
        passives=passives,
        source_count=d.get("source_count", 0),
        source_projects=d.get("source_projects", []),
        fingerprint=d.get("fingerprint", ""),
    )
