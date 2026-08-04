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

```
pip install AUMCdb_MEDS
MEDS_extract-AUMCdb input_dir=$RAW_DATA_DIR output_dir=$MEDS_DIR
```

If you want, you can also use the `do_download` flag to download the data directly from the AUMCdb repository.
You need to set the `AUMCDB_API_KEY` environment variable to your API key.
Please get it from
here: [AUMCdb API Key](https://lifesciences.datastations.nl/dataverseuser.xhtml?selectTab=dataRelatedToMe)

```
export AUMCDB_API_KEY=your_api_key
MEDS_extract-AUMCdb input_dir=$RAW_DATA_DIR output_dir=$MEDS_DIR
```

This will download the dataset automatically for you.

## Configuration

The entire ETL is described by one file, `src/AUMCdb_MEDS/configs/messy.yaml` — a
[MESSY](https://github.com/mmcdermott/MEDS_extract) config carrying three sections:

- **`sources:`** — where the raw data lives. `meds-extract-download` stages it, with SHA-256
    verification and resumable transfers. AmsterdamUMCdb's DANS DataVerse API key is passed as
    an `X-Dataverse-key` request header, read from `${oc.env:AUMCDB_API_KEY}` so the credential
    never lands in the config, the logs, or the output tree. This replaces the old `download.py`.
- **`etl:`** — the dataset name plus curated stage options (`n_subjects_per_shard`).
- **the event tables** — what to extract, written in
    [dftly](https://github.com/mmcdermott/dftly) expressions.

Because the config is registered under the `MEDS_extract.pipelines` entry-point group, the
extraction half is runnable directly, without this package's CLI wrapper:

```bash
# Stage the raw data only:
meds-extract-download spec=AUMCdb output_dir=$RAW_DATA_DIR

# Run the canonical 8-stage pipeline over already-pre-MEDS'd data:
meds-extract-run spec=AUMCdb output_dir=$MEDS_DIR download_key=null input_dir=$PRE_MEDS_DIR
```

The `MEDS_extract-AUMCdb` wrapper still exists because AmsterdamUMCdb needs a pre-MEDS step that
MESSY cannot yet express: unzipping the DataVerse archives and deriving the patient table's
pseudo-timestamps from admission offsets.
