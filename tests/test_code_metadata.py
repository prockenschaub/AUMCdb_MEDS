"""Code metadata: every event describes its codes, the public dictionary is pinned, the sources are
decoded with their declared encodings, and a synthetic build writes valid, described MEDS code
metadata."""

import re
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import yaml
from conftest import DICTIONARY_COLUMNS
from meds import CodeMetadataSchema

from AUMCdb_MEDS import MESSY_CFG

CFG = yaml.safe_load(MESSY_CFG.read_text())
NOT_TABLES = {"sources", "etl", "_defaults"}
DICTIONARY_PREFIX = "dictionary"
# Parents the ETL emits: only the dictionary's own item-level codes. Other vocabulary tagging
# (e.g. OMOP Gender) is left to suMEDS (`sumeds_rules.yaml`, tests/test_sumeds_rules.py).
OMOP_PARENT = re.compile(r"^(LOINC|ATC|SNOMED)/\S+$")


def _events():
    for table, body in CFG.items():
        if table in NOT_TABLES:
            continue
        for name, event in body.items():
            if name != "_table":
                yield table, name, event


def test_every_event_describes_its_codes():
    undescribed = [
        f"{table}/{name}"
        for table, name, event in _events()
        if not any(
            "description" in block for block in event.get("_metadata", {}).values()
        )
    ]
    assert not undescribed, undescribed


def test_dictionary_source_is_pinned():
    (entry,) = CFG["sources"]["common"]
    (url,) = entry["urls"]
    assert re.search(
        r"/AmsterdamUMC/AmsterdamUMCdb/[0-9a-f]{40}/amsterdamumcdb/dictionary/legacy/dictionary\.csv$",
        url["url"],
    ), url["url"]
    assert re.fullmatch(r"[0-9a-f]{64}", url["sha256"])
    assert url["rel_path"] == f"{DICTIONARY_PREFIX}.csv"


def test_dictionary_blocks_are_scoped_to_their_table():
    n_blocks = 0
    for table, name, event in _events():
        block = event.get("_metadata", {}).get(DICTIONARY_PREFIX)
        if block is None:
            continue
        n_blocks += 1
        assert block["item"] == "$item", f"{table}/{name}"
        referenced = set(re.findall(r"\$(\w+)", " ".join(map(str, block.values()))))
        assert referenced <= set(DICTIONARY_COLUMNS), (
            f"{table}/{name}",
            referenced - set(DICTIONARY_COLUMNS),
        )
        for out in ("description", "parent_codes"):
            assert block[out].endswith(f'if $table == "{table}"'), (
                f"{table}/{name}.{out}"
            )
    assert n_blocks == 10


def test_only_dictionary_blocks_add_parent_codes():
    """The ETL's parents come from AmsterdamUMC's dictionary; suMEDS adds the Gender tags."""
    with_parents = {
        f"{table}/{name}"
        for table, name, event in _events()
        for prefix, block in event.get("_metadata", {}).items()
        if "parent_codes" in block and prefix != DICTIONARY_PREFIX
    }
    assert not with_parents, with_parents


def test_every_source_declares_its_encoding():
    """MEDS-Extract >= 0.8 decodes event and `_metadata` csv sources with `etl.encoding`, and
    detects the codec of any source it does not list. Every source is declared: the data tables
    as Windows-1252, the dictionary as UTF-8."""
    encoding = CFG["etl"]["encoding"]
    tables = {table for table in CFG if table not in NOT_TABLES}
    assert set(encoding) == tables | {DICTIONARY_PREFIX}
    assert {encoding[table] for table in tables} == {"cp1252"}
    assert encoding[DICTIONARY_PREFIX] == "utf8"


def test_sources_are_decoded_with_their_declared_encodings(codes: pl.DataFrame):
    """Non-ASCII item names, units and values of the cp1252 tables survive, and the UTF-8
    dictionary (with its byte-order mark) still joins on them and keeps its own non-ASCII text."""
    rows = {row["code"]: row for row in codes.to_dicts()}
    assert {
        "MEASURE//Synthetische temperatuur//°C",
        "MEASURE//Synthetisch bewustzijn//0//Geïrriteerd",
        "DRUG//DOSE//Synthetische injecties//Synthetisch vaatmiddel//µg",
    } <= set(rows)
    weight = rows["MEASURE//Patiëntgewicht//kg"]
    assert weight["description"].startswith(
        "patient weight (synthetic) (Patiëntgewicht): "
    )
    assert "itemid 9003, category Synthetische metingen µ°)" in weight["description"]
    assert weight["parent_codes"] == ["LOINC/29463-7"]


def test_synthetic_build_writes_described_valid_code_metadata(meds_output: Path):
    table = pq.read_table(meds_output / "metadata" / "codes.parquet")
    CodeMetadataSchema.validate(
        table
    )  # as read from disk: string / list<string>, not large_string
    codes = pl.from_arrow(table)
    assert codes["description"].str.contains("\n").not_().all(), (
        "descriptions from two blocks merged"
    )
    parents = pl.Series(
        [p for ps in codes["parent_codes"].to_list() if ps for p in ps], dtype=pl.String
    )
    assert parents.str.contains(OMOP_PARENT.pattern).all(), parents.to_list()
    assert parents.str.starts_with("SNOMED/").any()

    # Every admissions code is described from its own components.
    admissions = codes.filter(
        pl.col("code").str.contains(
            r"^(MEDS_BIRTH|MEDS_DEATH|GENDER|ICU_|WEIGHT_|HEIGHT_)"
        )
    )
    assert admissions.height > 0 and admissions["description"].null_count() == 0

    # Every item event gets descriptions, from its own table's dictionary rows only.
    for table_name, name, event in _events():
        if DICTIONARY_PREFIX not in event.get("_metadata", {}):
            continue
        described = codes.filter(pl.col("code_template") == event["code"])[
            "description"
        ]
        assert described.len() > 0, f"{table_name}/{name}: no code described"
        assert described.str.contains(f"AmsterdamUMCdb {table_name} itemid").all(), (
            f"{table_name}/{name}"
        )
