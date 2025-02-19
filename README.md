# AUMCdb MEDS Extraction ETL

This pipeline extracts the AUMCdb dataset into MEDS format. 

## Usage:

```
git clone https://github.com/prockenschaub/AUMCdb_MEDS.git
cd AUMCdb_MEDS
pip install .
MEDS_extract-AUMCdb input_dir=$RAW_DATA_DIR output_dir=$MEDS_DIR
```

> [!NOTE]
> To use this repository, you first need to download the AUMCdb database and unzip it. Please refer to the [AUMCdb Github page](https://github.com/AmsterdamUMC/AmsterdamUMCdb) for more information on how to get access to the data. 

## Examples:

There is currently no publically available demo dataset for AUMCdb. However, you can refer to the [MIMIC_IV_MEDS](https://github.com/mmcdermott/MIMIC_IV_MEDS) respository for an example of how to run a MEDS ETL pipeline. 

