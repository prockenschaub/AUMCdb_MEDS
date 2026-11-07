"""`suMEDS-extract spec=AUMCdb` runs the ETL and then suMEDS enrichment, offline.

This package registers its rules in suMEDS's `sumeds.rules` entry-point group under the same name
as its MEDS-Extract spec, so `suMEDS-extract` finds them from `spec=AUMCdb` alone. The ontology
source is a tiny pack repository in suMEDS's `sumeds-ontologies/0.1` layout, built here with
made-up titles for the LOINC codes of the synthetic dictionary of ``conftest.py``, so the test reads
nothing over the network and does not depend on the published packs.
"""

import csv
import hashlib
import io
import json
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest
from conftest import run_command
from meds import CodeMetadataSchema

# vocabulary -> (release, codes). LOINC terms have no parents in the pack. LOINC 2951-2, the parent
# reference of MEASURE//Synthetisch natrium//mmol/l, is deliberately missing, so that code must
# stay unidentified. suMEDS has no pack for Gender, ATC or SNOMED CT.
PACKS = {"LOINC": ("2.83", ["8867-4", "29463-7"])}


def title(vocabulary: str, code: str) -> str:
    return f"Synthetic {vocabulary} title {code}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _names(value) -> dict[str, str]:
    """A names map as a dict: Polars 2 reads a Parquet map as a dict, Polars 1 as key/value structs."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {entry["key"]: entry["value"] for entry in value}


@pytest.fixture(scope="session")
def ontology_source(tmp_path_factory) -> Path:
    """A local `sumeds-ontologies/0.1` repository holding the synthetic LOINC pack."""
    root = tmp_path_factory.mktemp("ontologies")
    columns = ["code", "description", "parent", "first_year", "last_year"]
    vocabularies = {}
    for vocabulary, (release, codes) in PACKS.items():
        directory = root / vocabulary / release
        directory.mkdir(parents=True)
        by_shard: dict[str, list[list[str]]] = {}
        for code in codes:
            by_shard.setdefault(code[:1], []).append(
                [code, title(vocabulary, code), "", "", ""]
            )
        shards = {}
        for key, shard_rows in by_shard.items():
            buffer = io.StringIO()
            writer = csv.writer(buffer, lineterminator="\n")
            writer.writerows([columns, *shard_rows])
            data = buffer.getvalue().encode()
            (directory / f"{key}.csv").write_bytes(data)
            shards[key] = {
                "file": f"{key}.csv",
                "rows": len(shard_rows),
                "bytes": len(data),
                "sha256": _sha256(data),
            }
        manifest = {
            "schema": "sumeds-ontology-pack/0.1",
            "vocabulary": vocabulary,
            "release": release,
            "columns": columns,
            "fields": {
                "code": "code",
                "description": "description",
                "parent": "parent",
            },
            "shard_key_length": 1,
            "rows": len(codes),
            "bytes": sum(s["bytes"] for s in shards.values()),
            "shards": shards,
        }
        manifest_bytes = json.dumps(manifest).encode()
        (directory / "manifest.json").write_bytes(manifest_bytes)
        vocabularies[vocabulary] = {
            "manifest": f"{vocabulary}/{release}/manifest.json",
            "sha256": _sha256(manifest_bytes),
            "release": release,
            "rows": manifest["rows"],
            "bytes": manifest["bytes"],
        }
    index = {"schema": "sumeds-ontologies/0.1", "vocabularies": vocabularies}
    (root / "index.json").write_text(json.dumps(index))
    return root


@pytest.fixture(scope="session")
def enriched_output(tmp_path_factory, raw_dir: Path, ontology_source: Path) -> Path:
    output_dir = tmp_path_factory.mktemp("aumcdb_enriched") / "MEDS_cohort"
    run_command(
        [
            "suMEDS-extract",
            "spec=AUMCdb",
            f"output_dir={output_dir}",
            "do_download=false",
            f"input_dir={raw_dir}",
            "--",
            "--ontology-source",
            str(ontology_source),
            "--offline",
        ]
    )
    return output_dir


@pytest.fixture(scope="session")
def enriched_codes(enriched_output: Path) -> pl.DataFrame:
    return pl.read_parquet(enriched_output / "metadata" / "codes.parquet")


def test_codes_parquet_is_replaced_by_valid_meds_metadata(enriched_output: Path):
    metadata = enriched_output / "metadata"
    CodeMetadataSchema.validate(pq.read_table(metadata / "codes.parquet"))
    assert not list(metadata.glob(".*enriched*")), (
        "the temporary enrichment output was left behind"
    )


def test_data_matches_the_plain_etl(enriched_output: Path, events: pl.DataFrame):
    enriched_events = pl.concat(
        [pl.read_parquet(fp) for fp in (enriched_output / "data").rglob("*.parquet")]
    )
    key = ["subject_id", "time", "code"]
    assert enriched_events.sort(key).select(key).equals(events.sort(key).select(key))


def test_enrichment_keeps_what_the_etl_wrote(
    enriched_codes: pl.DataFrame, codes: pl.DataFrame
):
    """Non-destructive: every code keeps its description, and its ETL parents stay first, in order."""
    enriched = {row["code"]: row for row in enriched_codes.to_dicts()}
    assert set(enriched) == set(codes["code"])
    for row in codes.to_dicts():
        new = enriched[row["code"]]
        assert new["description"] == row["description"], row["code"]
        old_parents = row["parent_codes"] or []
        assert (new["parent_codes"] or [])[: len(old_parents)] == old_parents, row[
            "code"
        ]


def test_gender_codes_are_tagged_with_omop_gender_concepts(
    enriched_codes: pl.DataFrame,
):
    """Without Athena, the `validate: none` gender rule tags the code: it adds only the OMOP
    Gender code as parent, with no name and no vocabulary fields."""
    rows = {row["code"]: row for row in enriched_codes.to_dicts()}
    for code, concept in [("GENDER//Man", "M"), ("GENDER//Vrouw", "F")]:
        row = rows[code]
        assert row["parent_codes"] == [f"Gender//{concept}"], code
        assert not _names(row["parent_names"]), code
        assert row["vocabulary_id"] is None, code
    assert not rows["GENDER//UNK"]["parent_codes"]


def test_loinc_parent_references_are_identified_and_named(enriched_codes: pl.DataFrame):
    rows = {row["code"]: row for row in enriched_codes.to_dicts()}

    # The dictionary's LOINC parent identifies the code and gets its LOINC name; the ETL's
    # description is kept.
    heart_rate = rows["MEASURE//Synthetische hartslag///min"]
    assert heart_rate["parent_codes"] == ["LOINC/8867-4"]
    assert _names(heart_rate["parent_names"]) == {
        "LOINC/8867-4": title("LOINC", "8867-4")
    }
    assert (heart_rate["vocabulary_id"], heart_rate["concept_code"]) == (
        "LOINC",
        "8867-4",
    )
    assert heart_rate["description"].startswith(
        "synthetic heart rate (Synthetische hartslag): "
    )
    weight = rows["MEASURE//Patiëntgewicht//kg"]
    assert _names(weight["parent_names"]) == {
        "LOINC/29463-7": title("LOINC", "29463-7")
    }

    # A LOINC reference missing from the pack, and the ATC and SNOMED CT references (no pack), are
    # left alone.
    for code, parent in [
        ("MEASURE//Synthetisch natrium//mmol/l", "LOINC/2951-2"),
        (
            "DRUG//DOSE//Synthetische injecties//Synthetisch vaatmiddel//µg",
            "ATC/C01CA03",
        ),
        ("PROCESS//START//Synthetische lijn", "SNOMED/392230005"),
    ]:
        assert rows[code]["parent_codes"] == [parent], code
        assert not _names(rows[code]["parent_names"]), code
        assert rows[code]["vocabulary_id"] is None, code
