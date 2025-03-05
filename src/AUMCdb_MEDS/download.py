import logging
import zipfile
from getpass import getpass
from pathlib import Path

from omegaconf import DictConfig

from .commands import run_command


def download_data(
    output_dir: Path,
    dataset_info: DictConfig,
    do_demo: bool = False,
    runner_fn: callable = run_command,
):
    """Downloads the data specified in dataset_info.dataset_urls to the output_dir.

    Args:
        output_dir: The directory to download the data to.
        dataset_info: The dataset information containing the URLs to download.
        do_demo: Not currently available for AUMCdb; retained for compatibility
            but will raise an error if True.
        runner_fn: The function to run the command with (added for dependency injection).

    Raises:
        ValueError: If the command fails

    Examples:
        >>> cfg = DictConfig({
        ...     "urls": {
        ...         "dataset": [{
        ...             "url": "http://example.com/dataset",
        ...             "api_key": "abcdefg123"
        ...         }]
        ...     }
        ... })
        >>> def fake_shell_succeed(cmd):
        ...     print(" ".join(cmd))
        >>> download_data(Path("data"), cfg, runner_fn=fake_shell_succeed)
        curl -L -o data/AUMCdb.zip -H X-Dataverse-key:abcdefg123 http://example.com/dataset
    """

    if do_demo:
        raise ValueError("Demo download is not currently available for AUMCdb.")
    else:
        urls = dataset_info.get("urls", [])  # .get(["numeric_items","dataset"], [])

        for i, entry in enumerate(urls):
            url = urls[entry][0].get("url", None)
            if url is None:
                url = input("Enter the download link: ")

            key = urls[entry][0].get("api_key", None)
            if key is None:
                key = getpass("Enter your API Token: ")

            output_file = urls[entry][0].get("output_file", None)

            # output_file = output_dir #/ f"AUMCdb_{i}"

            if (output_dir / output_file).exists():
                logging.info(f"Removing existing file {output_file}")
                output_file.unlink()
            command_parts = ["cd", str(output_dir), "&&"]
            command_parts.extend(["curl", "-L", "-O", "-J", "-H", f"X-Dataverse-key:{key}", url])

            try:
                runner_fn(command_parts)
            except ValueError as e:
                raise ValueError(f"Failed to download data from {url}") from e

            with zipfile.ZipFile(output_file, "r") as zip_ref:
                zip_ref.extractall(output_dir)
            logging.info(f"Downloaded and extracted data to {output_dir}")

            if output_file.exists():
                logging.info(f"Removing zipped file {output_file}")
                output_file.unlink()
