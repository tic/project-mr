from pathlib import Path
from typing import List, Dict, Any
import whisper
from .logger import setup_logger

logger = setup_logger(__name__)


class SpeechProcessingError(Exception):
    """Exception raised when speech processing fails."""
    pass


class SpeechProcessor:
    """
    Handles speech-to-text processing using OpenAI Whisper.
    """

    def __init__(self, model_name: str = "base"):
        """
        Initialize the speech processor.

        Args:
            model_name: Whisper model to use (tiny, base, small, medium, large)
        """
        self.model_name = model_name
        self.model = None
        logger.info(f"Initializing Whisper model: {model_name}")

    def load_model(self):
        """Load the Whisper model if not already loaded."""
        if self.model is None:
            logger.info(f"Loading Whisper model '{self.model_name}'...")
            try:
                self.model = whisper.load_model(self.model_name)
                logger.info(f"Model '{self.model_name}' loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Whisper model: {e}")
                raise SpeechProcessingError(f"Failed to load model: {e}")

    def process_audio(self, audio_path: Path) -> List[Dict[str, Any]]:
        """
        Process audio file and extract speech segments with timestamps.

        Args:
            audio_path: Path to the audio file (WAV format expected)

        Returns:
            List of segment dictionaries with id, start, end, and text

        Raises:
            SpeechProcessingError: If processing fails
        """
        if not audio_path.exists():
            raise SpeechProcessingError(f"Audio file does not exist: {audio_path}")

        # Ensure model is loaded
        self.load_model()

        logger.info(f"Processing audio file: {audio_path.name}")

        try:
            # Transcribe audio with Whisper
            result = self.model.transcribe(
                str(audio_path),
                verbose=False,
                word_timestamps=False  # Segment-level timestamps only
            )

            # Extract segments
            segments = []
            for segment in result.get('segments', []):
                segments.append({
                    'id': segment['id'],
                    'start': round(segment['start'], 2),
                    'end': round(segment['end'], 2),
                    'text': segment['text'].strip()
                })

            logger.info(f"Extracted {len(segments)} speech segment(s)")
            return segments

        except Exception as e:
            logger.error(f"Speech processing failed: {e}")
            raise SpeechProcessingError(f"Failed to process audio: {e}")

    def get_language(self, audio_path: Path) -> str:
        """
        Detect the language of the audio.

        Args:
            audio_path: Path to the audio file

        Returns:
            Detected language code

        Raises:
            SpeechProcessingError: If detection fails
        """
        self.load_model()

        try:
            # Load audio and pad/trim to 30 seconds
            audio = whisper.load_audio(str(audio_path))
            audio = whisper.pad_or_trim(audio)

            # Make log-Mel spectrogram
            mel = whisper.log_mel_spectrogram(audio).to(self.model.device)

            # Detect language
            _, probs = self.model.detect_language(mel)
            detected_language = max(probs, key=probs.get)

            logger.info(f"Detected language: {detected_language}")
            return detected_language

        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return "unknown"
