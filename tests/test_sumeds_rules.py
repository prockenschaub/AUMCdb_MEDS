"""The packaged suMEDS rules file is well formed and matches the codes this ETL writes.

suMEDS (https://github.com/rvandewater/SumMEDS) reads `src/AUMCdb_MEDS/sumeds_rules.yaml` to add
vocabulary tags the dataset does not carry itself. These checks mirror its strict
`sumeds-rules/0.1` loader without depending on it, and build the example codes by evaluating the
code templates of `configs/messy.yaml` on made-up values, so a change to a code layout that breaks
a rule fails here.
"""

import re
from pathlib import Path

import polars as pl
import pytest
import yaml
from dftly import Parser

from AUMCdb_MEDS import MESSY_CFG, SUMEDS_RULES

CFG = yaml.safe_load(MESSY_CFG.read_text())
NOT_TABLES = {"sources", "etl", "_defaults"}

TOP_KEYS = {"schema", "ontology", "crosswalk", "hierarchy"}
ONTOLOGY_KEYS = {"id", "pattern", "vocabulary", "normalize", "validate"}
CROSSWALK_KEYS = {"id", "pattern", "table", "key_column", "code_column", "vocabulary"}
CROSSWALK_KEYS |= {"where", "normalize", "validate"}
HIERARCHY_KEYS = {"id", "pattern", "group", "mode", "separator", "ignore"}
HIERARCHY_KEYS |= {"nearest_only", "from_ontology", "rules"}


def _rules() -> dict:
    return yaml.safe_load(SUMEDS_RULES.read_text(encoding="utf-8"))


def _codes(table: str, event: str, **values) -> list[str]:
    """Evaluate the code template of ``table``/``event`` on rows of the given column values.

    Columns the template references but ``values`` omits get a made-up string; a first admission
    is assumed, as birth, death and gender are only emitted for it.
    """
    template = CFG[table][event]["code"]
    n = len(next(iter(values.values()))) if values else 1
    columns = {"admissioncount": [1] * n}
    for name in re.findall(r"\$(\w+)", template):
        columns.setdefault(name, [f"made-up {name}"] * n)
    df = pl.DataFrame(columns | values)
    return df.select(Parser()(template).polars_expr).to_series().to_list()


def _vocabulary_code(rule: dict, code: str) -> str | None:
    match = re.search(rule["pattern"], code)
    if match is None:
        return None
    value = match["code"]
    for step in rule.get("normalize") or []:
        value = re.sub(step["pattern"], step["replace"], value)
    return value


def test_rules_file_is_well_formed():
    rules = _rules()
    assert set(rules) <= TOP_KEYS
    assert rules["schema"] == "sumeds-rules/0.1"
    ids = []
    for rule in rules.get("ontology") or []:
        assert set(rule) <= ONTOLOGY_KEYS
        assert {"id", "pattern", "vocabulary"} <= set(rule)
        assert "code" in re.compile(rule["pattern"]).groupindex
        ids.append(rule["id"])
    for rule in rules.get("crosswalk") or []:
        assert set(rule) <= CROSSWALK_KEYS
        assert {"id", "pattern", "table", "key_column", "code_column"} <= set(rule)
        assert "key" in re.compile(rule["pattern"]).groupindex
        ids.append(rule["id"])
    for rule in (rules.get("ontology") or []) + (rules.get("crosswalk") or []):
        assert "/" not in rule["vocabulary"]
        assert rule.get("validate", "pack") in {"pack", "athena", "none"}
        for step in rule.get("normalize") or []:
            assert set(step) == {"pattern", "replace"}
            re.compile(step["pattern"])
    for rule in rules.get("hierarchy") or []:
        assert set(rule) <= HIERARCHY_KEYS
        if not rule.get("from_ontology"):
            assert rule["group"] in re.compile(rule["pattern"]).groupindex
        ids.append(rule["id"])
    assert len(ids) == len(set(ids)), "rule ids must be unique"


def test_rules_are_package_data():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '"sumeds_rules.yaml"' in pyproject


def test_gender_rule_maps_to_omop_gender_concepts():
    (rule,) = [r for r in _rules()["ontology"] if r["id"] == "aumcdb-gender"]
    assert rule["vocabulary"] == "Gender"
    codes = _codes("admissions", "gender", gender=["Man", "Vrouw", None, "unexpected"])
    assert codes == [
        "GENDER//Man",
        "GENDER//Vrouw",
        "GENDER//UNK",
        "GENDER//unexpected",
    ]
    assert [_vocabulary_code(rule, code) for code in codes] == ["M", "F", None, None]


def test_rules_match_no_other_code_layout():
    other = [
        code
        for table, body in CFG.items()
        if table not in NOT_TABLES
        for name in body
        if name != "_table" and not (table, name) == ("admissions", "gender")
        for code in _codes(table, name)
        if code is not None
    ]
    assert len(other) >= 15, "no codes built; the config parsing is stale"
    for rule in _rules()["ontology"]:
        assert not any(re.search(rule["pattern"], code) for code in other), rule["id"]


def test_rules_load_in_sumeds():
    """When suMEDS with rules support is installed, its own strict loader accepts the file."""
    ontology = pytest.importorskip("sumeds.ontology")
    rules = ontology.load_rules(Path(str(SUMEDS_RULES)))
    assert [rule.id for rule in rules.ontology] == ["aumcdb-gender"]
    assert not rules.hierarchy and not rules.crosswalk
