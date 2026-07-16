"""Stable identifiers shared by semantic and structural extraction."""
import re
from pathlib import Path


def normalize_id(text: str) -> str:
    """Normalize string to ASTify node ID: [a-z0-9_]."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s]', '', text)
    text = re.sub(r'\s+', '_', text)
    return text[:80]


def stem_from_path(filepath: Path, root: Path) -> str:
    """Build node ID stem: {parent_dir}_{filename_without_ext}."""
    rel = filepath.relative_to(root)
    parts = rel.parts
    fname_stem = normalize_id(filepath.stem)
    if len(parts) > 1:
        parent = normalize_id(parts[-2])
        return f'{parent}_{fname_stem}'
    return fname_stem
