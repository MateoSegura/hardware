"""Export a ParsedProject to JSON.

Handles serialization of Path objects and dataclasses to produce
a clean, pretty-printed JSON output.
"""

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from src.pipeline.models import ParsedProject


def _default_serializer(obj):
    """Custom JSON serializer for types not handled by json.dumps."""
    if isinstance(obj, Path):
        return str(obj)
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _convert_paths(obj):
    """Recursively convert Path objects to strings in a nested structure."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _convert_paths(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_paths(item) for item in obj]
    return obj


def export_project(project: ParsedProject) -> str:
    """Export a ParsedProject to a pretty-printed JSON string.

    Path objects are serialized as strings. Includes a stats summary
    at the top level.
    """
    data = asdict(project)
    data = _convert_paths(data)
    return json.dumps(data, indent=2, default=_default_serializer)


def export_project_to_file(project: ParsedProject, output_path: Path) -> None:
    """Export a ParsedProject to a JSON file."""
    json_str = export_project(project)
    output_path.write_text(json_str)
