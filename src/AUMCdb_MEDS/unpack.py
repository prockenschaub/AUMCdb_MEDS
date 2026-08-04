"""Unpack the DataVerse zip archives staged by `meds-extract-download`.

AmsterdamUMCdb ships as zip archives, and MEDS-Extract's download layer has no post-fetch
archive unpack yet (mmcdermott/MEDS_extract#92), so this small step stands between
`meds-extract-download` and the pre-MEDS transform. It preserves the behaviour the old
`download.py` had inline: extract each archive in place, then remove it.

Once MEDS_extract#92 lands, this module can be deleted and the `sources:` block can declare the
unpack directly.
"""

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)


def unpack_archives(input_dir: Path, do_overwrite: bool = False) -> list[Path]:
    """Extract every ``*.zip`` directly inside ``input_dir``, then delete the archive.

    Extraction preserves the archive's internal directory structure, matching what the previous
    `download.py` did with ``ZipFile.extractall``.

    Args:
        input_dir: The directory holding the downloaded archives.
        do_overwrite: If False (the default), an archive whose members are all already present on
            disk is skipped and left in place, so re-running is cheap and non-destructive. If
            True, members are re-extracted unconditionally.

    Returns:
        The archives that were extracted, in sorted order. Archives skipped because their contents
        were already present are not included.

    Raises:
        FileNotFoundError: If ``input_dir`` does not exist.

    Examples:
        >>> import tempfile, zipfile
        >>> tmp = Path(tempfile.mkdtemp())
        >>> with zipfile.ZipFile(tmp / "data.zip", "w") as zf:
        ...     zf.writestr("admissions.csv", "patientid,admittedattime\\n1,0\\n")
        ...     zf.writestr("nested/numericitems.csv", "patientid,item\\n1,HR\\n")
        >>> [p.name for p in unpack_archives(tmp)]
        ['data.zip']
        >>> sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*") if p.is_file())
        ['admissions.csv', 'nested/numericitems.csv']

        The archive itself is removed once extracted:

        >>> (tmp / "data.zip").exists()
        False

        A second run is a no-op rather than an error:

        >>> unpack_archives(tmp)
        []

        Already-extracted archives are left alone unless `do_overwrite` is set:

        >>> with zipfile.ZipFile(tmp / "again.zip", "w") as zf:
        ...     zf.writestr("admissions.csv", "patientid,admittedattime\\n1,0\\n")
        >>> unpack_archives(tmp)
        []
        >>> (tmp / "again.zip").exists()
        True
        >>> [p.name for p in unpack_archives(tmp, do_overwrite=True)]
        ['again.zip']

        A missing directory is an error, not a silent no-op:

        >>> unpack_archives(tmp / "nope")
        Traceback (most recent call last):
            ...
        FileNotFoundError: No such input directory: ...nope
    """
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"No such input directory: {input_dir}")

    extracted = []
    for archive in sorted(input_dir.glob("*.zip")):
        with zipfile.ZipFile(archive) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            already_present = all((input_dir / m.filename).exists() for m in members)
            if members and already_present and not do_overwrite:
                logger.info(
                    "Skipping %s: all %d members already extracted (pass do_overwrite=True to "
                    "force).",
                    archive.name,
                    len(members),
                )
                continue

            logger.info("Extracting %s (%d members) to %s", archive.name, len(members), input_dir)
            zf.extractall(input_dir)

        archive.unlink()
        extracted.append(archive)

    return extracted
