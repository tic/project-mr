import os
import tempfile
from pathlib import Path
import ffmpeg
from .logger import setup_logger

logger = setup_logger(__name__)


class AudioExtractionError(Exception):
    """Exception raised when audio extraction fails."""
    pass


def extract_audio(media_file: Path, output_path: Path = None) -> Path:
    """
    Extract audio from a media file and convert to 16kHz mono WAV.

    Args:
        media_file: Path to the input media file
        output_path: Optional path for the output audio file.
                    If not provided, creates a temporary file.

    Returns:
        Path to the extracted audio file

    Raises:
        AudioExtractionError: If extraction fails
    """
    if not media_file.exists():
        raise AudioExtractionError(f"Media file does not exist: {media_file}")

    # Create output path if not provided
    if output_path is None:
        # Create temporary file
        fd, temp_path = tempfile.mkstemp(suffix='.wav', prefix='quotefinder_')
        os.close(fd)
        output_path = Path(temp_path)

    logger.info(f"Extracting audio from: {media_file.name}")

    try:
        # Use ffmpeg to extract audio
        # -vn: no video
        # -acodec pcm_s16le: 16-bit PCM
        # -ar 16000: sample rate 16kHz (Whisper's expected rate)
        # -ac 1: mono audio
        stream = ffmpeg.input(str(media_file))
        stream = ffmpeg.output(
            stream,
            str(output_path),
            acodec='pcm_s16le',
            ar=16000,
            ac=1,
            vn=None
        )
        ffmpeg.run(stream, capture_stdout=True, capture_stderr=True, overwrite_output=True)

        logger.info(f"Audio extracted to: {output_path}")
        return output_path

    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg error extracting audio from {media_file.name}: {error_message}")

        # Clean up failed output file
        if output_path.exists():
            output_path.unlink()

        raise AudioExtractionError(f"Failed to extract audio: {error_message}")


def get_media_duration(media_file: Path) -> float:
    """
    Get the duration of a media file in seconds.

    Args:
        media_file: Path to the media file

    Returns:
        Duration in seconds

    Raises:
        AudioExtractionError: If probing fails
    """
    try:
        probe = ffmpeg.probe(str(media_file))
        duration = float(probe['format']['duration'])
        return duration
    except (ffmpeg.Error, KeyError, ValueError) as e:
        logger.error(f"Failed to get duration for {media_file.name}: {e}")
        raise AudioExtractionError(f"Failed to probe media file: {e}")


def cleanup_temp_audio(audio_path: Path) -> None:
    """
    Clean up temporary audio file.

    Args:
        audio_path: Path to the audio file to delete
    """
    try:
        if audio_path.exists():
            audio_path.unlink()
            logger.debug(f"Cleaned up temporary audio file: {audio_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up temporary audio file {audio_path}: {e}")
