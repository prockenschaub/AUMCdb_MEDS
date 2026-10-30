"""Code metadata: every event describes its codes, the public dictionary is pinned, and a synthetic
build writes valid, described MEDS code metadata."""

import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
import yaml
from dftly import Parser
from meds import CodeMetadataSchema

from AUMCdb_MEDS import MESSY_CFG, PIPELINE_NAME

CFG = yaml.safe_load(MESSY_CFG.read_text())
NOT_TABLES = {"sources", "etl", "_defaults"}
DICTIONARY_PREFIX = "dictionary"
# Header of amsterdamumcdb/dictionary/legacy/dictionary.csv at the commit pinned in `sources.common`.
DICTIONARY_COLUMNS = {
    "itemid", "item", "item_en", "vocabulary_id", "vocabulary_concept_code", "vocabulary_concept_name",
    "abbreviation", "categoryid", "category", "category_en", "ordercategoryid", "ordercategory",
    "islabresult", "valueid", "value", "unitid", "unit", "ucum_code", "low_normal_value",
    "high_normal_value", "expected_min_value", "expected_max_value", "table", "count", "count_validated",
}  # fmt: skip
OMOP_PARENT = re.compile(r"^(LOINC|ATC|SNOMED|Gender)/\S+$")
# The CLIs live next to the interpreter; the pipeline also spawns its stage CLI through PATH.
ENV = os.environ | {
    "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
}


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
        assert referenced <= DICTIONARY_COLUMNS, (
            f"{table}/{name}",
            referenced - DICTIONARY_COLUMNS,
        )
        for out in ("description", "parent_codes"):
            assert block[out].endswith(f'if $table == "{table}"'), (
                f"{table}/{name}.{out}"
            )
    assert n_blocks == 10


def test_gender_parent_codes_are_omop_gender_concepts():
    expr = Parser()(
        CFG["admissions"]["gender"]["_metadata"]["_self"]["parent_codes"]
    ).polars_expr
    genders = pl.DataFrame({"gender": ["Man", "Vrouw", None, "unexpected"]})
    assert genders.select(expr.alias("parent"))["parent"].to_list() == [
        "Gender/M",
        "Gender/F",
        None,
        None,
    ]


def _write_fixture_dictionary(raw_dir: Path) -> None:
    """Replace MESSY-synth's dictionary by a fixture in the published format.

    MESSY-synth fills `table` with placeholders that match no table, so no item code would be
    described. The fixture gives each synthetic item exactly one table (an item name belongs to one
    table in AmsterdamUMCdb too), and alternates English names and vocabulary codes. It is written
    like the published file: UTF-8 with a byte-order mark, every column text.
    """
    items = sorted(
        pl.read_parquet(raw_dir / f"{DICTIONARY_PREFIX}.parquet")["item"]
        .drop_nulls()
        .unique()
    )
    (raw_dir / f"{DICTIONARY_PREFIX}.parquet").unlink()
    tables = [
        "numericitems",
        "listitems",
        "freetextitems",
        "procedureorderitems",
        "processitems",
        "drugitems",
    ]
    vocab = [
        ("LOINC", "718-7"),
        ("SNOMED CT", "271649006"),
        ("ATC", "B05XA05"),
        ("", ""),
    ]
    with open(
        raw_dir / f"{DICTIONARY_PREFIX}.csv", "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(f, fieldnames=sorted(DICTIONARY_COLUMNS))
        writer.writeheader()
        for i, item in enumerate(items):
            vocabulary_id, vocabulary_code = vocab[i % len(vocab)]
            writer.writerow(
                {c: "" for c in DICTIONARY_COLUMNS}
                | {
                    "itemid": str(1000 + i),
                    "item": item,
                    "item_en": f"english name {i}" if i % 2 == 0 else "",
                    "category": f"category {i}",
                    "table": tables[i % len(tables)],
                    "vocabulary_id": vocabulary_id,
                    "vocabulary_concept_code": vocabulary_code,
                }
            )


@pytest.mark.skipif(
    shutil.which("MESSY-synth", path=ENV["PATH"]) is None, reason="needs MESSY-synth"
)
def test_synthetic_build_writes_described_valid_code_metadata(tmp_path):
    raw_dir, out_dir = tmp_path / "raw", tmp_path / "meds"
    subprocess.run(
        ["MESSY-synth", PIPELINE_NAME, "-o", str(raw_dir), "-q"], check=True, env=ENV
    )
    _write_fixture_dictionary(raw_dir)
    run = [
        "meds-extract-run",
        f"spec={PIPELINE_NAME}",
        f"output_dir={out_dir}",
        f"input_dir={raw_dir}",
    ]
    subprocess.run([*run, "do_download=false"], check=True, env=ENV)

    table = pq.read_table(out_dir / "metadata" / "codes.parquet")
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
