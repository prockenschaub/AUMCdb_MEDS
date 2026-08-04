# AUMCdb MEDS Extraction ETL

[![PyPI - Version](https://img.shields.io/pypi/v/AUMCdb-MEDS)](https://pypi.org/project/AUMCdb-MEDS)
[![license](https://img.shields.io/badge/License-MIT-green.svg?labelColor=gray)](https://github.com/mmcdermott/ETL_MEDS_Template#license)
[![PRs](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mmcdermott/ETL_MEDS_Template/pulls)
![contributors](https://img.shields.io/github/contributors/mmcdermott/ETL_MEDS_Template.svg)
![Static Badge](https://img.shields.io/badge/MEDS-0.3.3-blue)
[![DOI](https://zenodo.org/badge/902929228.svg)](https://doi.org/10.5281/zenodo.17531824)

This pipeline extracts the AUMCdb dataset into MEDS format. The AUMCdb dataset is a publicly available dataset from the
Amsterdam University Medical Centers (AUMC) that contains clinical data from the hospital. You first need to request
access [here](https://lifesciences.datastations.nl/dataset.xhtml?persistentId=doi:10.17026/dans-22u-f8vd).

## Usage:

```bash
pip install AUMCdb_MEDS

# Get your API key from
# https://lifesciences.datastations.nl/dataverseuser.xhtml?selectTab=dataRelatedToMe
export AUMCDB_API_KEY=your_api_key

meds-extract-run spec=AUMCdb output_dir=$MEDS_DIR
```

That single command downloads the DataVerse archives, unpacks them, and runs the full
eight-stage MEDS-Extract pipeline. To stage the raw data separately:

```bash
meds-extract-download spec=AUMCdb output_dir=$RAW_DATA_DIR
meds-extract-run spec=AUMCdb output_dir=$MEDS_DIR download_key=null input_dir=$RAW_DATA_DIR
```

## Configuration

**This package contains no ETL code.** The entire pipeline is one file,
[`src/AUMCdb_MEDS/configs/messy.yaml`](src/AUMCdb_MEDS/configs/messy.yaml), registered under the
`MEDS_extract.pipelines` entry-point group. It carries three sections:

- **`sources:`** — where the raw data lives. The DANS DataVerse API key is passed as an
  `X-Dataverse-key` header read from `${oc.env:AUMCDB_API_KEY}`, so the credential never lands in
  the config, the logs, or the output tree. Both entries are zips, unpacked by the download layer.
- **`etl:`** — the dataset name and curated stage options.
- **the event tables** — what to extract, in [dftly](https://github.com/mmcdermott/dftly)
  expressions.

### Pseudo-timestamps

AUMCdb stores only *offsets* (in milliseconds) from a per-admission origin; absolute times are not
meaningful, only relative differences. Reconstructing real timestamps used to be a Python
pre-MEDS step; it is now `_table.cols`:

```yaml
_origin: '(((extract /2003|2010/ from $admissionyeargroup)::int)::year)::datetime'
admittedattime: '$_origin + ($admittedat / 1000)::seconds'
```

Tables other than `admissions` key on `admissionid`, so each joins `admissions` for the subject id
and year group before rebuilding `_origin`.

