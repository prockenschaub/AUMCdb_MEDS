"""Code metadata: every event describes its codes, the public dictionary is pinned, the sources are
decoded with their declared encodings, and a synthetic build writes valid, described MEDS code
metadata."""

import json
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
OMOP_PARENT = re.compile(r"^(LOINC|ATC|SNOMED)//[^/]+$")


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
    # The dictionary's LOINC parent, then its unit-free stem (`link_single_units`).
    assert weight["parent_codes"] == ["LOINC//29463-7", "MEASURE//Patiëntgewicht"]


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
    # Besides vocabulary references, the only parents are in-dataset: the code without the unit,
    # given to every code that ends in its unit (test_unit_siblings_get_their_stem_as_parent_and_row).
    in_dataset = parents.is_in(codes["code"].implode())
    assert parents.filter(~in_dataset).str.contains(OMOP_PARENT.pattern).all(), (
        parents.to_list()
    )
    for code, ps in zip(codes["code"].to_list(), codes["parent_codes"].to_list(), strict=True):
        in_dataset_parents = [p for p in ps or [] if p in set(codes["code"])]
        assert len(in_dataset_parents) <= 1, code
        assert all(code.startswith(f"{p}//") for p in in_dataset_parents), code
    assert "DRUG//DOSE//Synthetische injecties//Synthetisch vaatmiddel" in set(parents)
    assert parents.str.starts_with("SNOMED//").any()

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


def test_numeric_codes_carry_their_unit(codes: pl.DataFrame):
    """Every code with a numeric value gets the unit of its own rows as `unit` metadata: as recorded
    (`unit_source_value`), the same raw value as the code's last component, so the codes themselves
    are unchanged; in `unit`, written in UCUM by suMEDS's `sumeds_normalize_units`."""
    # MEDS-Extract (>= 0.9) writes it as one String per code.
    assert codes.schema["unit"] == pl.String
    units = dict(zip(codes["code"], codes["unit"].to_list(), strict=True))
    recorded = dict(
        zip(codes["code"], codes["unit_source_value"].to_list(), strict=True)
    )
    # code -> (unit in UCUM, unit as recorded)
    expected = {
        "MEASURE//Synthetische temperatuur//°C": ("Cel", "°C"),
        "MEASURE//Synthetische hartslag///min": ("/min", "/min"),
        "DRUG//DOSE//Synthetische injecties//Synthetisch vaatmiddel//µg": ("ug", "µg"),
        "DRUG//RATE//Synthetische infusen//Synthetisch infuus//ml/uur": (
            "mL/h",
            "ml/uur",
        ),
    }
    for code, unit in expected.items():
        assert (units[code], recorded[code]) == unit, code
    numeric = codes.filter(
        (
            pl.col("code").str.starts_with("DRUG//RATE//")
            | pl.col("code").str.starts_with("DRUG//DOSE//")
            | pl.col("code_template").str.contains("units", literal=True)
        )
        & pl.col("code_template").is_not_null()  # stem rows have no template
    )
    assert numeric.height == 9
    for code, unit in zip(
        numeric["code"], numeric["unit_source_value"].to_list(), strict=True
    ):
        assert code.endswith(f"//{unit}"), code
    # Codes without a numeric value have no unit.
    assert units["MEASURE//Synthetisch bewustzijn//0//Alert"] is None
    assert (
        units["DRUG//START//Synthetische injecties//Synthetisch vaatmiddel//Nieuwe zak"]
        is None
    )
    assert units["MEDS_BIRTH"] is None


def test_unit_siblings_get_their_stem_as_parent_and_row(codes: pl.DataFrame):
    """Two dose codes of one drug that differ only in their unit share the code without the unit as
    parent, and that code gets a row: no unit, the description and vocabulary parents they share."""
    rows = {row["code"]: row for row in codes.iter_rows(named=True)}
    stem = "DRUG//DOSE//Synthetische injecties//Synthetisch vaatmiddel"
    siblings = [f"{stem}//µg", f"{stem}//mg"]
    for code in siblings:
        assert rows[code]["parent_codes"][-1] == stem, code
    assert rows[stem]["unit"] is None
    assert rows[stem]["description"] == rows[siblings[0]]["description"]
    assert rows[stem]["description"] == rows[siblings[1]]["description"]
    vocabulary = [p for p in rows[siblings[0]]["parent_codes"] if p != stem]
    assert (rows[stem]["parent_codes"] or []) == vocabulary
    # A unit-suffixed code without a sibling gets its stem too (`link_single_units`).
    rate = "DRUG//RATE//Synthetische infusen//Synthetisch infuus"
    assert rows[rate]["unit"] is None
    assert rows[f"{rate}//ml/uur"]["parent_codes"][-1] == rate


def test_events_carry_their_icu_admission(meds_output: Path, events: pl.DataFrame):
    """Every event but the patient-level ones carries its `admissionid` as `icustay_id`."""
    metadata = json.loads((meds_output / "metadata" / "dataset.json").read_text())
    assert metadata["raw_source_id_columns"] == ["icustay_id"]
    patient_level = pl.col("code").is_in(["MEDS_BIRTH", "MEDS_DEATH"]) | pl.col(
        "code"
    ).str.starts_with("GENDER//")
    assert events.filter(patient_level)["icustay_id"].is_null().all()
    stays = events.filter(~patient_level)
    assert stays["icustay_id"].is_not_null().all()
    # Patient 1's two admissions stay apart; every item table maps back to its admission.
    assert set(
        stays.filter(pl.col("subject_id") == 1)["icustay_id"].unique().to_list()
    ) == {11, 12}
    assert set(stays["icustay_id"].unique().to_list()) == {11, 12, 21, 31, 41, 51}
    processes = stays.filter(pl.col("code").str.starts_with("PROCESS//"))
    assert dict(zip(processes["subject_id"], processes["icustay_id"], strict=True)) == {
        1: 11,
        2: 21,
    }
