import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
from .logger import setup_logger

logger = setup_logger(__name__)


class StorageError(Exception):
    """Exception raised when storage operations fail."""
    pass


def save_transcription(
    output_path: Path,
    media_file: Path,
    segments: List[Dict[str, Any]],
    duration: float
) -> None:
    """
    Save transcription results to a JSON file.

    Args:
        output_path: Path where the JSON file should be saved
        media_file: Path to the original media file
        segments: List of transcription segments
        duration: Duration of the media file in seconds

    Raises:
        StorageError: If saving fails
    """
    try:
        # Create output directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the output structure
        data = {
            'media_file': str(media_file.absolute()),
            'media_filename': media_file.name,
            'processed_at': datetime.utcnow().isoformat() + 'Z',
            'duration_seconds': round(duration, 2),
            'segments': segments,
            'total_segments': len(segments)
        }

        # Write to temporary file first, then rename (atomic operation)
        temp_path = output_path.with_suffix('.tmp')

        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Atomic rename
        temp_path.replace(output_path)

        logger.info(f"Saved transcription to: {output_path}")

    except Exception as e:
        logger.error(f"Failed to save transcription: {e}")
        # Clean up temp file if it exists
        if temp_path.exists():
            temp_path.unlink()
        raise StorageError(f"Failed to save transcription: {e}")


def load_transcription(json_path: Path) -> Dict[str, Any]:
    """
    Load a transcription from a JSON file.

    Args:
        json_path: Path to the JSON file

    Returns:
        Dictionary containing the transcription data

    Raises:
        StorageError: If loading fails
    """
    try:
        if not json_path.exists():
            raise StorageError(f"JSON file does not exist: {json_path}")

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {json_path}: {e}")
        raise StorageError(f"Invalid JSON file: {e}")
    except Exception as e:
        logger.error(f"Failed to load transcription: {e}")
        raise StorageError(f"Failed to load transcription: {e}")


def get_full_text(json_path: Path) -> str:
    """
    Extract the full transcribed text from a JSON file.

    Args:
        json_path: Path to the JSON file

    Returns:
        Complete transcribed text

    Raises:
        StorageError: If loading fails
    """
    data = load_transcription(json_path)
    segments = data.get('segments', [])
    return ' '.join(segment['text'] for segment in segments)
