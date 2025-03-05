import logging
import zipfile
from getpass import getpass
from pathlib import Path

from omegaconf import DictConfig

from .commands import run_command


def download_data(
    output_dir: Path,
    dataset_info: DictConfig,
    runner_fn: callable = run_command,
):
    """Downloads the data specified in dataset_info.dataset_urls to the output_dir.

    Args:
        output_dir: The directory to download the data to.
        dataset_info: The dataset information containing the URLs to download.
        do_demo: If True, download the demo URLs instead of the main URLs.
        runner_fn: The function to run the command with (added for dependency injection).

    Raises:
        ValueError: If the command fails

    Examples:
        >>> cfg = DictConfig({
        ...     "url": "http://example.com/dataset",
        ...     "api_key": "[MY_API_KEY]"
        ... })
        >>> def fake_shell_succeed(cmd):
        ...     print(" ".join(cmd))
        >>> def fake_shell_fail(cmd):
        ...     raise ValueError(f"Failed to run {' '.join(cmd)}")
        >>> download_data(Path("data"), cfg, runner_fn=fake_shell_succeed)
        wget -r -N -c -np -nH --directory-prefix data http://example.com/dataset
        wget -r -N -c -np -nH --directory-prefix data http://example.com/common
        >>> download_data(Path("data"), cfg, runner_fn=fake_shell_fail)
        Traceback (most recent call last):
            ...
        ValueError: Failed to download data from http://example.com/dataset
        >>> cfg = DictConfig({"urls": {"dataset": [{"url": "http://example.com/data", "username": "foo"}]}})
        >>> download_data(Path("data_out"), cfg, runner_fn=fake_shell_succeed)
        wget -r -N -c -np -nH --directory-prefix data_out --user foo --ask-password http://example.com/data
    """

    url = dataset_info.get("url", None)
    if url is None:
        url = getpass("Enter the download link: ")

    output_file = output_dir / "AUMCdb.zip"

    if output_file.exists():
        logging.info(f"Removing existing file {output_file}")
        output_file.unlink()

    key = dataset_info.get("api_key", None)
    if key is None:
        key = getpass("Enter your API Token: ")

    command_parts = ["curl", "-L", "-o", str(output_file), "-H", f"X-Dataverse-key:{key}", url]

    try:
        runner_fn(command_parts)
    except ValueError as e:
        raise ValueError(f"Failed to download data from {url}") from e

    with zipfile.ZipFile(output_file, "r") as zip_ref:
        zip_ref.extractall(output_dir)
    logging.info(f"Downloaded and extracted data to {output_dir}")

    if output_file.exists():
        logging.info(f"Removing existing file {output_file}")
        output_file.unlink()
