# AUMCdb MEDS Extraction ETL

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
