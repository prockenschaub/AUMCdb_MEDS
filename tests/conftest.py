"""A tiny, fully synthetic AmsterdamUMCdb-shaped dataset and one ETL run over it, shared by the tests.

AmsterdamUMCdb needs a data use agreement, so CI cannot download it. Instead this writes a handful
of made-up rows with the column layout of the AmsterdamUMCdb v1.0.2 tables
(https://github.com/AmsterdamUMC/AmsterdamUMCdb/wiki) and a small item dictionary in the format of
the published one, and runs ``meds-extract-run`` on them with ``do_download=false``. No values here
come from the real dataset or from the published dictionary.

The files reproduce what the config has to handle in the real release:

- the six item tables are Windows-1252 and use non-ASCII item names, units and values
  (``Patiëntgewicht``, ``°C``, ``µg``), while ``admissions.csv`` is plain ASCII;
- the dictionary is UTF-8 with a byte-order mark, every column text, and names the same non-ASCII
  items as the tables, so its join only matches if both encodings are decoded correctly;
- times are millisecond offsets from the first admission, with ``measuredat == -1899`` rows that
  must be dropped, and age is only an age band;
- birth, death and gender are only emitted for a patient's first admission, and a missing gender
  becomes ``GENDER//UNK``;
- list items have one dictionary row per list value, and one item name also has a dictionary row
  of another table, which must not describe this table's codes.

MESSY-synth (https://github.com/mmcdermott/MESSY_synth) generated the synthetic data before, but it
still pins ``MEDS-extract<0.8``, so it cannot be installed next to this package.
"""

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

# The CLIs live next to the interpreter; meds-extract-run also spawns its stage CLIs, and
# suMEDS-extract finds meds-extract-run, through PATH.
ENV = os.environ | {
    "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ.get('PATH', '')}"
}

# Patients 1-5 (MEDS-Extract needs >= 1 per train/tuning/held_out split). Offsets are milliseconds
# from the patient's first admission.
#   patient 1: two admissions (2003-2009); the second emits no birth, death or gender.
#   patient 2: died in the ICU (2010-2016), age band 80+.
#   patient 3: no gender, weight or height recorded.
#   patients 4 and 5: one admission each.
ADMISSIONS = """\
patientid,admissionid,admissioncount,location,urgency,origin,admittedat,admissionyeargroup,\
dischargedat,lengthofstay,destination,gender,agegroup,dateofdeath,weightgroup,weightsource,\
heightgroup,heightsource,specialty
1,11,1,IC,0,Synthetische afdeling,0,2003-2009,172800000,48,15,Man,60-69,,70-79,Gemeten,\
170-179,Anamnestisch,Synthetisch specialisme A
1,12,2,MC,1,Synthetische afdeling,2592000000,2003-2009,2678400000,24,16,Man,60-69,,70-79,Geschat,\
170-179,Geschat,Synthetisch specialisme A
2,21,1,IC&MC,1,,0,2010-2016,259200000,72,Overleden,Vrouw,80+,259200000,60-69,Anamnestisch,\
160-169,Gemeten,Synthetisch specialisme B
3,31,1,IC,0,Synthetische afdeling,0,2010-2016,86400000,24,15,,18-39,,,,,,Synthetisch specialisme C
4,41,1,IC,1,,0,2003-2009,86400000,24,15,Vrouw,40-49,,80-89,Gemeten,180-189,Gemeten,\
Synthetisch specialisme B
5,51,1,MC,0,,0,2010-2016,86400000,24,16,Man,50-59,,90-99,Geschat,190-199,Geschat,\
Synthetisch specialisme C
"""

# Item tables, written as Windows-1252. Item names are made up but Dutch-like; one per table, plus
# a lab item. The second Patiëntgewicht row has the -1899 offset that must be dropped.
NUMERICITEMS = """\
admissionid,itemid,item,tag,value,unitid,unit,comment,measuredat,registeredat,registeredby,\
updatedat,updatedby,islabresult,fluidout
11,9001,Synthetische hartslag,,80,1,/min,,3600000,3600000,ICV_IC-Verpleegkundig,,,0,
11,9002,Synthetische temperatuur,,37.2,2,°C,,7200000,7200000,ICV_IC-Verpleegkundig,,,0,
11,9003,Patiëntgewicht,,74.5,3,kg,,7200000,7200000,ICV_IC-Verpleegkundig,,,0,
21,9003,Patiëntgewicht,,61,3,kg,,-1899,0,ICV_IC-Verpleegkundig,,,0,
21,9004,Synthetisch natrium,,139,4,mmol/l,,3600000,3700000,Systeem,,,1,
31,9001,Synthetische hartslag,,95,1,/min,,1800000,1800000,ICV_IC-Verpleegkundig,,,0,
41,9002,Synthetische temperatuur,,38.1,2,°C,,1800000,1800000,ICV_IC-Verpleegkundig,,,0,
51,9001,Synthetische hartslag,,70,1,/min,,1800000,1800000,ICV_IC-Verpleegkundig,,,0,
"""

LISTITEMS = """\
admissionid,itemid,item,valueid,value,measuredat,registeredat,registeredby,updatedat,updatedby,\
islabresult
11,9101,Synthetisch bewustzijn,1,Geïrriteerd,3600000,3600000,ICV_IC-Verpleegkundig,,,0
21,9101,Synthetisch bewustzijn,2,Alert,3600000,3600000,ICV_IC-Verpleegkundig,,,0
41,9102,Synthetische kweek,1,Positief,3600000,3600000,Systeem,,,1
"""

FREETEXTITEMS = """\
admissionid,itemid,item,value,comment,measuredat,registeredat,registeredby,updatedat,updatedby,\
islabresult
11,9201,Synthetische opmerking,Synthetische notitie à la carte,,3600000,3600000,ICV_IC-Verpleegkundig,,,0
51,9202,Synthetische uitslag,Synthetisch resultaat,,3600000,3600000,Systeem,,,1
"""

PROCEDUREORDERITEMS = """\
admissionid,orderid,ordercategoryid,ordercategoryname,itemid,item,registeredat,registeredby
11,1,1,Synthetische handelingen,9301,Synthetische wondzorg,3600000,ICV_IC-Verpleegkundig
31,2,1,Synthetische handelingen,9301,Synthetische wondzorg,1800000,ICV_IC-Verpleegkundig
"""

PROCESSITEMS = """\
admissionid,itemid,item,start,stop,duration
11,9401,Synthetische lijn,0,86400000,1440
21,9401,Synthetische lijn,600000,250000000,4157
"""

DRUGITEMS = """\
admissionid,orderid,ordercategoryid,ordercategory,itemid,item,isadditive,isconditional,rate,\
rateunit,rateunitid,ratetimeunitid,doserateperkg,dose,doseunit,doserateunit,doseunitid,\
doserateunitid,administered,administeredunit,administeredunitid,action,start,stop,duration,\
solutionitemid,solutionitem,solutionadministered,solutionadministeredunit,fluidin,iscontinuous
11,1,1,Synthetische injecties,9501,Synthetisch vaatmiddel,0,0,2.5,ml/uur,1,1,0,4,µg,µg/min,1,1,\
50,ml,1,Nieuwe zak,3600000,7200000,60,,,,,,1
21,2,2,Synthetische infusen,9502,Synthetisch infuus,0,0,0,ml/uur,1,1,0,500,ml,,2,,500,ml,2,,\
600000,4200000,60,,,,,,0
"""

ITEM_TABLES = {
    "numericitems": NUMERICITEMS,
    "listitems": LISTITEMS,
    "freetextitems": FREETEXTITEMS,
    "procedureorderitems": PROCEDUREORDERITEMS,
    "processitems": PROCESSITEMS,
    "drugitems": DRUGITEMS,
}

# Header of amsterdamumcdb/dictionary/legacy/dictionary.csv at the commit pinned in
# `sources.common`, in its order.
DICTIONARY_COLUMNS = [
    "itemid", "item", "item_en", "vocabulary_id", "vocabulary_concept_code", "vocabulary_concept_name",
    "abbreviation", "categoryid", "category", "category_en", "ordercategoryid", "ordercategory",
    "islabresult", "valueid", "value", "unitid", "unit", "ucum_code", "low_normal_value",
    "high_normal_value", "expected_min_value", "expected_max_value", "table", "count", "count_validated",
]  # fmt: skip

# One row per item (and per list value for list items), with these columns; the others are empty.
# The LOINC codes are in the tiny pack of test_run_with_enrichment.py; suMEDS has no ATC or SNOMED
# CT pack.
DICTIONARY_ROW_COLUMNS = (
    "table",
    "itemid",
    "item",
    "item_en",
    "category",
    "category_en",
    "vocabulary_id",
    "vocabulary_concept_code",
    "value",
)
DICTIONARY_ROWS = [
    ("numericitems", 9001, "Synthetische hartslag", "synthetic heart rate", "Synthetische vitale functies",
     "synthetic vitals", "LOINC", "8867-4", ""),
    ("numericitems", 9002, "Synthetische temperatuur", "", "Synthetische vitale functies", "synthetic vitals",
     "", "", ""),
    ("numericitems", 9003, "Patiëntgewicht", "patient weight (synthetic)", "Synthetische metingen µ°",
     "", "LOINC", "29463-7", ""),
    ("numericitems", 9004, "Synthetisch natrium", "", "Synthetisch lab", "synthetic lab", "LOINC", "2951-2",
     ""),
    ("listitems", 9101, "Synthetisch bewustzijn", "synthetic consciousness", "Synthetische neurologie", "",
     "SNOMED CT", "271649006", "Geïrriteerd"),
    ("listitems", 9101, "Synthetisch bewustzijn", "synthetic consciousness", "Synthetische neurologie", "",
     "SNOMED CT", "271649006", "Alert"),
    ("listitems", 9102, "Synthetische kweek", "", "Synthetisch lab", "synthetic lab", "", "", "Positief"),
    # The same name as a numeric item, in another table: it must not describe MEASURE//Synthetische
    # hartslag//... codes.
    ("listitems", 9103, "Synthetische hartslag", "", "Synthetische vitale functies", "", "", "", "Regulair"),
    ("freetextitems", 9201, "Synthetische opmerking", "synthetic remark", "Synthetische teksten", "", "", "",
     ""),
    ("freetextitems", 9202, "Synthetische uitslag", "", "Synthetisch lab", "synthetic lab", "", "", ""),
    ("procedureorderitems", 9301, "Synthetische wondzorg", "synthetic wound care", "Synthetische zorg", "",
     "", "", ""),
    ("processitems", 9401, "Synthetische lijn", "synthetic line", "Synthetische lijnen", "", "SNOMED CT",
     "392230005", ""),
    ("drugitems", 9501, "Synthetisch vaatmiddel", "synthetic vasopressor", "Synthetische medicatie", "",
     "ATC", "C01CA03", ""),
    ("drugitems", 9502, "Synthetisch infuus", "", "Synthetische vloeistoffen", "synthetic fluids", "", "", ""),
]  # fmt: skip


def _dictionary_bytes() -> bytes:
    """The fixture dictionary, written like the published file: UTF-8 with a byte-order mark."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=DICTIONARY_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for values in DICTIONARY_ROWS:
        row = dict(zip(DICTIONARY_ROW_COLUMNS, map(str, values), strict=True))
        writer.writerow(dict.fromkeys(DICTIONARY_COLUMNS, "") | row)
    return buffer.getvalue().encode("utf-8-sig")


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory) -> Path:
    """The synthetic tables and dictionary, written as the raw AmsterdamUMCdb files."""
    raw_dir = tmp_path_factory.mktemp("aumcdb_raw")
    (raw_dir / "admissions.csv").write_bytes(ADMISSIONS.encode("ascii"))
    for name, content in ITEM_TABLES.items():
        (raw_dir / f"{name}.csv").write_bytes(content.encode("cp1252"))
    (raw_dir / "dictionary.csv").write_bytes(_dictionary_bytes())
    return raw_dir


def run_command(argv: list[str]) -> None:
    """Run a CLI, failing the test with its full output if it does not succeed."""
    result = subprocess.run(argv, capture_output=True, text=True, env=ENV)
    assert result.returncode == 0, (
        f"{argv[0]} failed with exit code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


@pytest.fixture(scope="session")
def meds_output(tmp_path_factory, raw_dir: Path) -> Path:
    output_dir = tmp_path_factory.mktemp("aumcdb") / "MEDS_cohort"
    run_command(
        [
            "meds-extract-run",
            "spec=AUMCdb",
            f"output_dir={output_dir}",
            "do_download=false",
            f"input_dir={raw_dir}",
        ]
    )
    return output_dir


@pytest.fixture(scope="session")
def events(meds_output: Path) -> pl.DataFrame:
    return pl.concat(
        [pl.read_parquet(fp) for fp in (meds_output / "data").rglob("*.parquet")]
    )


@pytest.fixture(scope="session")
def codes(meds_output: Path) -> pl.DataFrame:
    return pl.read_parquet(meds_output / "metadata" / "codes.parquet")
