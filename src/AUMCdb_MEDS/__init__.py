"""AmsterdamUMCdb MEDS ETL -- a pure-config MEDS-Extract pipeline.

This package contains no ETL code. The entire pipeline is `configs/messy.yaml`, registered under
the `MEDS_extract.pipelines` entry-point group, so it runs as:

    meds-extract-run spec=AUMCdb output_dir=$OUTPUT_DIR
"""

from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files

__package_name__ = "AUMCdb_MEDS"
try:
    __version__ = version(__package_name__)
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

# The name this ETL registers under `MEDS_extract.pipelines`; `meds-extract-run spec=AUMCdb`
# resolves it, and MEDS-Extract uses it as the default dataset name.
PIPELINE_NAME = "AUMCdb"

MESSY_CFG = files(__package_name__).joinpath("configs/messy.yaml")
# Rules for suMEDS (https://github.com/rvandewater/SumMEDS), which adds the vocabulary parents
# this ETL leaves to it; see the README section "Enriching code metadata with suMEDS".
SUMEDS_RULES = files(__package_name__).joinpath("sumeds_rules.yaml")

__all__ = [
    "MESSY_CFG",
    "PIPELINE_NAME",
    "SUMEDS_RULES",
    "__package_name__",
    "__version__",
]
