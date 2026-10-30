# AUMCdb MEDS Extraction ETL

[![PyPI - Version](https://img.shields.io/pypi/v/AUMCdb-MEDS)](https://pypi.org/project/AUMCdb-MEDS)
[![synthetic-etl](https://github.com/prockenschaub/AUMCdb_MEDS/actions/workflows/synthetic-etl.yaml/badge.svg)](https://github.com/prockenschaub/AUMCdb_MEDS/actions/workflows/synthetic-etl.yaml)
[![code-quality](https://github.com/prockenschaub/AUMCdb_MEDS/actions/workflows/code-quality-main.yaml/badge.svg)](https://github.com/prockenschaub/AUMCdb_MEDS/actions/workflows/code-quality-main.yaml)
![python](https://img.shields.io/badge/-Python_3.11%20%7C%203.12%20%7C%203.13-blue?logo=python&logoColor=white)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/prockenschaub/AUMCdb_MEDS#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/prockenschaub/AUMCdb_MEDS/pulls)
[![contributors](https://img.shields.io/github/contributors/prockenschaub/AUMCdb_MEDS.svg)](https://github.com/prockenschaub/AUMCdb_MEDS/graphs/contributors)
[![DOI](https://zenodo.org/badge/902929228.svg)](https://doi.org/10.5281/zenodo.17531824)
[![MEDS v0.4](https://img.shields.io/badge/MEDS-0.4-blue)](https://medical-event-data-standard.github.io/)

An ETL pipeline that converts the [Amsterdam University Medical Centers Database
(AmsterdamUMCdb)](https://amsterdammedicaldatascience.nl/#access) into the
[Medical Event Data Standard (MEDS)](https://medical-event-data-standard.github.io/) using
[MEDS-Extract](https://github.com/mmcdermott/MEDS_extract).

AmsterdamUMCdb is a de-identified intensive care database from Amsterdam UMC. It covers about
23,000 ICU admissions of about 20,000 patients between 2003 and 2016, with vital signs, lab
results, medication, procedures and fluid balance. The data is freely available for research, but
you need to sign a data use agreement first. Request access through the
[DANS DataVerse](https://lifesciences.datastations.nl/dataset.xhtml?persistentId=doi:10.17026/dans-22u-f8vd).

- More information about AmsterdamUMCdb: https://github.com/AmsterdamUMC/AmsterdamUMCdb
- More information about MEDS: https://medical-event-data-standard.github.io/

This ETL targets AmsterdamUMCdb **v1.0.2**.

## Setup

Requires Python `>=3.11,<3.14` and MEDS-Extract `>=0.7.1`.

```bash
pip install AUMCdb_MEDS
```

Downloading the data needs a DANS DataVerse API key. You can create one on your
[DataVerse account page](https://lifesciences.datastations.nl/dataverseuser.xhtml?selectTab=dataRelatedToMe)
once your access request has been approved:

```bash
export AUMCDB_API_KEY=your_api_key
```

## Usage

```bash
meds-extract-run spec=AUMCdb output_dir=$MEDS_DIR
```

That single command downloads the DataVerse archives, unpacks them, and runs the full
eight-stage MEDS-Extract pipeline. To stage the raw data separately, or to use a copy you already
have:

```bash
meds-extract-download spec=AUMCdb output_dir=$RAW_DATA_DIR
meds-extract-run spec=AUMCdb output_dir=$MEDS_DIR do_download=false input_dir=$RAW_DATA_DIR
```

`$RAW_DATA_DIR` should contain the seven AUMCdb CSVs (`admissions.csv`, `numericitems.csv`,
`listitems.csv`, `freetextitems.csv`, `procedureorderitems.csv`, `processitems.csv` and
`drugitems.csv`) as distributed, without converting their encoding, plus the public item
dictionary `dictionary.csv` that the code descriptions are built from (see
[Code metadata](#code-metadata)). The download fetches it with the data; to add it to a copy you
already have (no API key needed):

```bash
meds-extract-download spec=AUMCdb output_dir=$RAW_DATA_DIR key=common
```

### Resources and parallelism

`numericitems.csv` alone is about 11 GB, so a full run needs a fair amount of memory and disk. You
can trade memory for parallelism with the optional extras:

```bash
pip install AUMCdb_MEDS[local_parallelism] # local parallelism with hydra-joblib-launcher
pip install AUMCdb_MEDS[slurm_parallelism] # parallelism on SLURM with hydra-submitit-launcher
```

The number of subjects per shard is set by `n_subjects_per_shard` under `etl:` in the config
(default 1000).

## Configuration

**This package contains no ETL code.** The entire pipeline is one file,
[`src/AUMCdb_MEDS/configs/messy.yaml`](src/AUMCdb_MEDS/configs/messy.yaml), registered under the
`MEDS_extract.pipelines` entry-point group. It carries three sections:

- **`sources:`** — where the raw data lives. The DANS DataVerse API key is passed as an
    `X-Dataverse-key` header read from `${oc.env:AUMCDB_API_KEY}`, so the credential never lands in
    the config, the logs, or the output tree. Both entries are zips, unpacked by the download layer.
    The `common` entry is the public item dictionary, pinned to a commit and checked by SHA-256.
- **`etl:`** — the dataset name and curated stage options, including `encoding: cp1252`: six of
    the seven source CSVs are Windows-1252, not UTF-8.
- **the event tables** — what to extract, in [dftly](https://github.com/mmcdermott/dftly)
    expressions.

### Pseudo-timestamps

AUMCdb stores only *offsets* (in milliseconds) relative to the patient's first ICU admission;
absolute times are not meaningful, only relative differences. Reconstructing real timestamps used to be a Python
pre-MEDS step; it is now `_table.cols`:

```yaml
_origin: (((extract /2003|2010/ from $admissionyeargroup)::int)::year)::datetime
admittedattime: $_origin + ($admittedat / 1000)::seconds
```

Tables other than `admissions` key on `admissionid`, so each joins `admissions` for the subject id
and year group before rebuilding `_origin`.

The anchor uses each admission's own `admissionyeargroup`. In v1.0.2 no patient's later admissions
fall in a different year group from their first, so this matches anchoring on the first admission.

### Source encoding

AmsterdamUMCdb ships its CSVs in Windows-1252 (only `admissions.csv` is plain ASCII). The config
declares `encoding: cp1252`, so MEDS-Extract decodes them correctly and non-ASCII characters in item
names and units survive intact. Decoding is strict: an invalid byte stops
the run instead of silently becoming `�`.

## Output

Each subject is one AUMCdb patient (`patientid`). Codes are built from the source columns, joined
with `//`, and a missing component becomes `UNK`:

| Code prefix                                        | Source table          | Value           |
| -------------------------------------------------- | --------------------- | --------------- |
| `MEDS_BIRTH`, `MEDS_DEATH`, `GENDER//…`            | `admissions`          |                 |
| `ICU_ADMISSION//…`, `ICU_DISCHARGE//…`             | `admissions`          |                 |
| `WEIGHT_AT_ADMISSION//…`, `HEIGHT_AT_ADMISSION//…` | `admissions`          |                 |
| `MEASURE//{item}//{unit}`                          | `numericitems`        | `numeric_value` |
| `MEASURE//{item}//{islabresult}//{value}`          | `listitems`           |                 |
| `MEASURE//{item}//{islabresult}`                   | `freetextitems`       | `text_value`    |
| `PROCEDURE//{ordercategoryname}//{item}`           | `procedureorderitems` |                 |
| `PROCESS//START//…`, `PROCESS//END//…`             | `processitems`        |                 |
| `DRUG//START//…`, `DRUG//END//…`                   | `drugitems`           |                 |
| `DRUG//RATE//…`, `DRUG//DOSE//…`                   | `drugitems`           | `numeric_value` |

Birth, death and gender are only emitted from a patient's first admission, and gender is static
(no timestamp). AUMCdb only reports age in bands (`40-49`, `80+`), so the birth date is imputed
from the middle of the band. Death is placed at its recorded offset. See the comments in the
config for the exact rules.

### Code metadata

`metadata/codes.parquet` lists every code with a `description`, `parent_codes` where a standard
vocabulary applies, and the `code_template` it was built from. Releases up to 0.1.0 wrote only the
`code` column. Codes are built from Dutch item names and admission categories, which a reader can
decode with the AmsterdamUMCdb documentation but which cross-dataset mapping and vocabulary
tooling (OHDSI Athena) cannot resolve, so the config now attaches the documented meaning:

| Code family                                                                                             | Route                                                                                                                                                                         | Source                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `MEASURE//…`, `PROCEDURE//…`, `PROCESS//…`, `DRUG//…`                                                   | `_metadata: dictionary:` blocks, joined on the item name and restricted to the dictionary rows of the event's own table; one entry covers every unit, value or action variant | the item dictionary AmsterdamUMC publishes for v1.0.2 and earlier ([`amsterdamumcdb/dictionary/legacy/dictionary.csv`](https://github.com/AmsterdamUMC/AmsterdamUMCdb/blob/5422b94dbaba6c1d9b7c301f059c425ca1fc13ce/amsterdamumcdb/dictionary/legacy/dictionary.csv), MIT, commit 5422b94), downloaded at ETL time: English item name where translated, Dutch item name, itemid, category; its LOINC, ATC or SNOMED CT code as parent code |
| `MEDS_BIRTH`, `MEDS_DEATH`, `GENDER//…`, `ICU_ADMISSION//…`, `ICU_DISCHARGE//…`, `WEIGHT_…`, `HEIGHT_…` | `_metadata: _self:` templates, evaluated per admission                                                                                                                        | the code's own components, named after their `admissions` column and explained as in the [AmsterdamUMCdb table documentation](https://github.com/AmsterdamUMC/AmsterdamUMCdb/wiki/admissions); `GENDER//Man` and `GENDER//Vrouw` get `Gender/M` and `Gender/F`, as in AmsterdamUMC's OMOP dictionary                                                                                                                                       |

Nothing from the dictionary is copied into this repository. It holds 4,985 items: 472 with an
English name and 387 mapped to a vocabulary (169 LOINC, 210 ATC, 8 SNOMED CT), so most item codes
are described by their Dutch name, itemid and category. On v1.0.2, every item name in each of the
six item tables has a dictionary row for that table (checked against the raw tables), so every
code gets a description.
The parent codes are AmsterdamUMC's own item-level mappings (made for the Dutch ICU data
warehouse); the vocabulary's own text is left to vocabulary tooling. MEDS 0.4 makes `description`
optional, so consumers must still not rely on it for datasets built with older releases.

## Testing with synthetic data

You can run the whole ETL without access to AmsterdamUMCdb.
[MESSY_synth](https://github.com/mmcdermott/MESSY_synth) reads the config, works out what the raw
tables must look like, and writes fake source files with the right shape. CI does this on every
pull request (see [`.github/workflows/synthetic-etl.yaml`](.github/workflows/synthetic-etl.yaml)):

```bash
pip install AUMCdb_MEDS MESSY-synth # MESSY-synth needs Python >= 3.12
MESSY-synth AUMCdb -o raw_synthetic/ --explain
meds-extract-run spec=AUMCdb output_dir=meds_synthetic/ do_download=false input_dir=raw_synthetic/
```

Every generated value is visibly fake, so the output is only useful for checking that the
pipeline runs end to end and that every event still produces rows. MESSY-synth's placeholder
dictionary matches no table, so its item codes stay undescribed; `pytest tests` (also run in CI)
rebuilds with a small fixture dictionary and checks that every event's codes are described and that
`codes.parquet` validates against the MEDS code-metadata schema.

## Contributing

Pull requests are welcome. Install the development extras and the pre-commit hooks first:

```bash
pip install -e .[dev]
pre-commit install
```

## Citation

If you use this ETL in your research, please cite it with the Zenodo DOI (also available through
GitHub's "Cite this repository" button):

```bibtex
@software{van_de_Water_AUMCdb_MEDS_ETL_2025,
  author = {van de Water, Robin and Rockenschaub, Patrick and Renc, Pawel and McDermott, Matthew},
  doi = {10.5281/zenodo.17531824},
  license = {MIT},
  title = {{The AUMCdb MEDS ETL}},
  url = {https://github.com/prockenschaub/AUMCdb_MEDS},
  year = {2025}
}
```

Please also cite the AmsterdamUMCdb dataset itself:

```bibtex
@article{thoralSharingICUPatient2021,
  title = {Sharing {{ICU Patient Data Responsibly Under}} the {{Society}} of {{Critical Care Medicine}}/{{European Society}} of {{Intensive Care Medicine Joint Data Science Collaboration}}: {{The Amsterdam University Medical Centers Database}} ({{AmsterdamUMCdb}}) {{Example}}*},
  shorttitle = {Sharing {{ICU Patient Data Responsibly Under}} the {{Society}} of {{Critical Care Medicine}}/{{European Society}} of {{Intensive Care Medicine Joint Data Science Collaboration}}},
  author = {Thoral, Patrick J. and Peppink, Jan M. and Driessen, Ronald H. and Sijbrands, Eric J. G. and Kompanje, Erwin J. O. and Kaplan, Lewis and Bailey, Heatherlee and Kesecioglu, Jozef and Cecconi, Maurizio and Churpek, Matthew and Clermont, Gilles and {van der Schaar}, Mihaela and Ercole, Ari and Girbes, Armand R. J. and Elbers, Paul W. G.},
  year = 2021,
  month = jun,
  journal = {Critical Care Medicine},
  volume = {49},
  number = {6},
  pages = {e563-e577},
  issn = {0090-3493},
  doi = {10.1097/CCM.0000000000004916},
  urldate = {2022-04-29},
  langid = {english},
}
```

## License

This ETL is released under the [MIT License](LICENSE). AmsterdamUMCdb itself is covered by its own
data use agreement.
