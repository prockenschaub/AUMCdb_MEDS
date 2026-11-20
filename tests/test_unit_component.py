"""A code's unit component is the row's unit stripped, and `UNK` when it is missing or blank.

MEDS-Extract compares units stripped and drops blank ones when it writes `codes.parquet`, so a
code that kept the whitespace would split one unit over several codes (` mg`, `mg`, `mg `), and a
blank one would give a code ending in whitespace (or in `//`) with no unit. The expressions are
evaluated straight from the shipped config with dftly, as MEDS-Extract evaluates them.
"""

from pathlib import Path

import polars as pl
import pytest
import yaml
from dftly import Parser

CONFIG_FP = Path(__file__).parents[1] / "src" / "AUMCdb_MEDS" / "configs" / "messy.yaml"

UNITS = ["mg", " mg", "mg ", "\tmg\n", "ml/uur", "  ", "", None]
EXPECTED = ["mg", "mg", "mg", "mg", "ml/uur", "UNK", "UNK", "UNK"]

# (table, event, unit helper, raw unit column, code prefix)
CASES = [
    ("numericitems", "event", "_value_unit", "unit", "MEASURE//Item A//"),
    ("drugitems", "rate", "_rate_unit", "rateunit", "DRUG//RATE//Cat//Item A//"),
    ("drugitems", "dose", "_dose_unit", "doseunit", "DRUG//DOSE//Cat//Item A//"),
]


@pytest.mark.parametrize("table,event,helper,column,prefix", CASES)
def test_unit_component_is_stripped_and_blank_is_unk(
    table, event, helper, column, prefix
):
    block = yaml.safe_load(CONFIG_FP.read_text())[table]
    raw = pl.DataFrame(
        {
            column: UNITS,
            "item": ["Item A"] * len(UNITS),
            "ordercategory": ["Cat"] * len(UNITS),
        },
        schema_overrides={column: pl.String},
    )
    with_cols = raw.with_columns(
        **Parser.to_polars({helper: block["_table"]["cols"][helper]})
    )
    codes = with_cols.select(**Parser.to_polars({"code": block[event]["code"]}))[
        "code"
    ].to_list()
    assert codes == [prefix + unit for unit in EXPECTED]
    # `unit` stays the raw column; MEDS-Extract strips it when it writes `codes.parquet`.
    assert block[event]["_metadata"]["_self"]["unit"] == f"${column}"
