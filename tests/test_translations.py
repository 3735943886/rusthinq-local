"""Custom integrations load translations/<lang>.json at runtime, never strings.json, so keep them in sync."""

import json
import re
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "rusthinq"
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
TRANSLATIONS = sorted((COMPONENT / "translations").glob("*.json"))


def _flat(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        if isinstance(value, dict):
            out.update(_flat(value, f"{prefix}{key}."))
        else:
            out[prefix + key] = value
    return out


def test_english_matches_strings():
    assert json.loads((COMPONENT / "translations" / "en.json").read_text()) == STRINGS


@pytest.mark.parametrize("path", TRANSLATIONS, ids=lambda p: p.name)
def test_translation_keys_and_placeholders(path: Path):
    source = _flat(STRINGS)
    translated = _flat(json.loads(path.read_text()))
    assert sorted(source.keys() - translated.keys()) == [], "missing keys"
    assert sorted(translated.keys() - source.keys()) == [], "extra keys"
    placeholder = re.compile(r"\{(\w+)\}")
    for key, text in source.items():
        assert set(placeholder.findall(translated[key])) == set(placeholder.findall(text)), key


@pytest.mark.parametrize("path", [COMPONENT / "strings.json", *TRANSLATIONS], ids=lambda p: p.name)
def test_no_key_appears_twice(path: Path):
    """A key given twice loads as its last value, dropping the first; a line merge of two branches that both add an
    `entity.<platform>` makes one."""
    def unique(pairs):
        keys = [key for key, _ in pairs]
        assert len(keys) == len(set(keys)), sorted({key for key in keys if keys.count(key) > 1})
        return dict(pairs)

    json.loads(path.read_text(), object_pairs_hook=unique)
