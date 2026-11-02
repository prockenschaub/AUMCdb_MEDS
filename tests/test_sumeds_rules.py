"""The packaged suMEDS rules file loads in suMEDS and matches the codes this ETL writes.

suMEDS (https://github.com/rvandewater/SumMEDS) reads `src/AUMCdb_MEDS/sumeds_rules.yaml` to add
vocabulary tags the dataset does not carry itself. Its strict `sumeds-rules/0.1` loader
(`sumeds.load_rules`) validates the file, and the rule objects its enrichment uses resolve the
example codes, so these tests only state what AmsterdamUMCdb's codes must resolve to. The example
codes are built by evaluating the code templates of `configs/messy.yaml` on made-up values, so a
change to a code layout that breaks a rule fails here.
"""

import re
from pathlib import Path

import polars as pl
import yaml
from dftly import Parser
from sumeds import load_rules

from AUMCdb_MEDS import MESSY_CFG, SUMEDS_RULES

CFG = yaml.safe_load(MESSY_CFG.read_text())
NOT_TABLES = {"sources", "etl", "_defaults"}


def _rules():
    return load_rules(Path(str(SUMEDS_RULES)))


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


def test_rules_are_package_data():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert '"sumeds_rules.yaml"' in pyproject


def test_rules_load_in_sumeds():
    """suMEDS's strict loader accepts the file, which holds only the gender rule."""
    rules = _rules()
    assert [rule.id for rule in rules.ontology] == ["aumcdb-gender"]
    assert not rules.hierarchy and not rules.crosswalk


def test_gender_rule_maps_to_omop_gender_concepts():
    (rule,) = _rules().ontology
    assert rule.vocabulary == "Gender"
    codes = _codes("admissions", "gender", gender=["Man", "Vrouw", None, "unexpected"])
    assert codes == [
        "GENDER//Man",
        "GENDER//Vrouw",
        "GENDER//UNK",
        "GENDER//unexpected",
    ]
    assert [rule.resolve(code) for code in codes] == ["M", "F", None, None]


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
    for rule in _rules().ontology:
        assert all(rule.resolve(code) is None for code in other), rule.id
