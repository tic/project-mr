import os
from pathlib import Path
from typing import List, Set
from .logger import setup_logger

logger = setup_logger(__name__)

# Default supported media file extensions
DEFAULT_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm'}


def scan_media_files(
    input_dir: str,
    output_dir: str = None,
    recursive: bool = True,
    extensions: Set[str] = None,
    skip_processed: bool = True
) -> List[Path]:
    """
    Scan directory for media files.

    Args:
        input_dir: Directory to scan for media files
        output_dir: Directory where JSON outputs are stored (to check for processed files)
        recursive: Whether to scan subdirectories
        extensions: Set of file extensions to include (default: common video formats)
        skip_processed: Whether to skip files that already have JSON output

    Returns:
        List of Path objects for media files to process
    """
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS

    # Normalize extensions to lowercase with dot prefix
    extensions = {ext.lower() if ext.startswith('.') else f'.{ext.lower()}' for ext in extensions}

    input_path = Path(input_dir)
    if not input_path.exists():
        logger.error(f"Input directory does not exist: {input_dir}")
        return []

    if not input_path.is_dir():
        logger.error(f"Input path is not a directory: {input_dir}")
        return []

    # Determine output directory for checking processed files
    if output_dir is None:
        output_dir = input_dir
    output_path = Path(output_dir)

    logger.info(f"Scanning {'recursively' if recursive else 'non-recursively'} in: {input_dir}")
    logger.info(f"Looking for extensions: {', '.join(sorted(extensions))}")

    media_files = []

    # Scan for media files
    if recursive:
        pattern = '**/*'
    else:
        pattern = '*'

    for file_path in input_path.glob(pattern):
        if file_path.is_file() and file_path.suffix.lower() in extensions:
            # Check if already processed
            if skip_processed and _is_processed(file_path, output_path):
                logger.debug(f"Skipping already processed file: {file_path}")
                continue

            media_files.append(file_path)

    logger.info(f"Found {len(media_files)} media file(s) to process")
    return media_files


def _is_processed(media_file: Path, output_dir: Path) -> bool:
    """
    Check if a media file has already been processed.

    Args:
        media_file: Path to the media file
        output_dir: Directory where JSON outputs are stored

    Returns:
        True if JSON output exists, False otherwise
    """
    # Generate expected JSON output path in /json subdirectory
    json_filename = media_file.stem + '.json'
    json_path = output_dir / "json" / json_filename

    return json_path.exists()


def get_output_path(media_file: Path, output_dir: str = None) -> Path:
    """
    Get the output JSON path for a media file.

    Args:
        media_file: Path to the media file
        output_dir: Directory where JSON outputs should be stored

    Returns:
        Path object for the JSON output file
    """
    if output_dir is None:
        # Save JSON next to the media file
        return media_file.with_suffix('.json')
    else:
        # Save JSON in specified output directory with /json subdirectory
        output_path = Path(output_dir) / "json"
        output_path.mkdir(parents=True, exist_ok=True)
        return output_path / (media_file.stem + '.json')
