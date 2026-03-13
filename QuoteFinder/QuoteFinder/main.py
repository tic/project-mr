import argparse
import sys
from pathlib import Path
from typing import Set

from .logger import setup_logger
from .media_scanner import scan_media_files, get_output_path
from .audio_extractor import extract_audio, get_media_duration, cleanup_temp_audio, AudioExtractionError
from .speech_processor import SpeechProcessor, SpeechProcessingError
from .storage import save_transcription, StorageError

logger = setup_logger("QuoteFinder")


def process_media_file(
    media_file: Path,
    output_dir: str,
    processor: SpeechProcessor,
    detect_language: bool = False
) -> bool:
    """
    Process a single media file.

    Args:
        media_file: Path to the media file
        output_dir: Directory for JSON output
        processor: SpeechProcessor instance
        detect_language: Whether to detect language

    Returns:
        True if successful, False otherwise
    """
    audio_path = None

    try:
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing: {media_file.name}")
        logger.info(f"{'='*60}")

        # Get media duration
        duration = get_media_duration(media_file)
        logger.info(f"Duration: {duration:.2f} seconds ({duration/60:.1f} minutes)")

        # Extract audio
        audio_path = extract_audio(media_file)

        # Detect language if requested
        language = None
        if detect_language:
            language = processor.get_language(audio_path)

        # Process speech
        segments = processor.process_audio(audio_path)

        # Save to JSON
        output_path = get_output_path(media_file, output_dir)
        save_transcription(
            output_path,
            media_file,
            segments,
            duration
        )

        logger.info(f"Successfully processed: {media_file.name}")
        return True

    except (AudioExtractionError, SpeechProcessingError, StorageError) as e:
        logger.error(f"Failed to process {media_file.name}: {e}")
        return False

    except Exception as e:
        logger.error(f"Unexpected error processing {media_file.name}: {e}")
        return False

    finally:
        # Clean up temporary audio file
        if audio_path:
            cleanup_temp_audio(audio_path)


def main():
    """Main entry point for QuoteFinder."""
    parser = argparse.ArgumentParser(
        description="QuoteFinder - Extract speech from media files with timestamps",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Process all media files in a directory:
    python -m QuoteFinder.main --input-dir /media

  Use a larger Whisper model for better accuracy:
    python -m QuoteFinder.main --input-dir /media --model small

  Save JSON files to a different directory:
    python -m QuoteFinder.main --input-dir /media --output-dir /output
        """
    )

    parser.add_argument(
        '--input-dir',
        type=str,
        default='/media',
        help='Directory to scan for media files'
    )

    parser.add_argument(
        '--output-dir',
        type=str,
        default='/output',
        help='Directory to save JSON files (default: same as input)'
    )

    parser.add_argument(
        '--model',
        type=str,
        default='base',
        choices=['tiny', 'base', 'small', 'medium', 'large'],
        help='Whisper model size (default: base)'
    )

    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Disable recursive directory scanning'
    )

    parser.add_argument(
        '--extensions',
        type=str,
        nargs='+',
        default=None,
        help='Media file extensions to process (default: mkv mp4 avi mov wmv flv webm)'
    )

    parser.add_argument(
        '--detect-language',
        action='store_true',
        help='Detect and record the language of each media file'
    )

    parser.add_argument(
        '--reprocess',
        action='store_true',
        help='Reprocess files that already have JSON output'
    )

    # Mode selectors
    parser.add_argument(
        '--scan',
        action='store_true',
        help='Scan and transcribe media files (can combine with other modes)'
    )

    parser.add_argument(
        '--store',
        action='store_true',
        help='Load JSON files into SQLite database (can combine with other modes)'
    )

    parser.add_argument(
        '--query',
        type=str,
        default=None,
        help='Search database for similar segments (enables query mode, can combine with other modes)'
    )

    # Database and query options
    parser.add_argument(
        '--db-path',
        type=str,
        default=None,
        help='Path to SQLite database file (default: <output-dir>/sqlite/quotefinder.db)'
    )

    parser.add_argument(
        '--query-limit',
        type=int,
        default=50,
        help='Maximum number of query results to return (default: 50)'
    )

    args = parser.parse_args()

    # Determine which modes are enabled
    scan_mode = args.scan
    store_mode = args.store
    query_mode = args.query is not None

    # If no modes selected, show usage and exit
    if not (scan_mode or store_mode or query_mode):
        parser.print_help()
        logger.error("\nError: No mode selected. Use --scan, --store, and/or --query")
        logger.info("\nExamples:")
        logger.info("  Scan only:           --scan --input-dir /media")
        logger.info("  Store only:          --store --input-dir /media")
        logger.info("  Query only:          --query 'search text' --output-dir /output")
        logger.info("  Scan + Store:        --scan --store --input-dir /media")
        logger.info("  Scan + Store + Query: --scan --store --query 'text' --input-dir /media")
        return 1

    logger.info("QuoteFinder - Multi-Mode Pipeline")
    logger.info(f"Enabled modes: {', '.join([m for m, enabled in [('scan', scan_mode), ('store', store_mode), ('query', query_mode)] if enabled])}\n")

    # Track overall success
    overall_success = True

    # Mode 1: Scan (transcription)
    if scan_mode:
        logger.info("="*60)
        logger.info("MODE 1: SCAN - Transcribing media files")
        logger.info("="*60)

        # Validate required arguments for scan mode
        if not args.input_dir:
            logger.error("--input-dir is required for scan mode")
            return 1

        # Parse extensions if provided
        extensions: Set[str] = None
        if args.extensions:
            extensions = set(args.extensions)

        logger.info(f"Input directory: {args.input_dir}")
        logger.info(f"Output directory: {args.output_dir or args.input_dir}")
        logger.info(f"Whisper model: {args.model}")

        media_files = scan_media_files(
            args.input_dir,
            args.output_dir,
            recursive=not args.no_recursive,
            extensions=extensions,
            skip_processed=not args.reprocess
        )

        if not media_files:
            logger.warning("No media files found to process")
        else:
            # Initialize speech processor
            processor = SpeechProcessor(model_name=args.model)

            # Process each file
            success_count = 0
            failure_count = 0

            try:
                for i, media_file in enumerate(media_files, 1):
                    logger.info(f"\nFile {i}/{len(media_files)}")

                    success = process_media_file(
                        media_file,
                        args.output_dir,
                        processor,
                        args.detect_language
                    )

                    if success:
                        success_count += 1
                    else:
                        failure_count += 1

            except KeyboardInterrupt:
                logger.warning("\n\nScan mode interrupted by user")
                overall_success = False

            finally:
                # Summary
                logger.info(f"\n{'='*60}")
                logger.info("Scan Mode Summary")
                logger.info(f"{'='*60}")
                logger.info(f"Successfully processed: {success_count}")
                logger.info(f"Failed: {failure_count}")
                logger.info(f"Total: {success_count + failure_count}\n")

                if failure_count > 0:
                    overall_success = False

    # Mode 2: Store (load JSON to database)
    if store_mode:
        logger.info("="*60)
        logger.info("MODE 2: STORE - Loading JSON files into database")
        logger.info("="*60)

        # Validate required arguments for store mode
        if not args.input_dir:
            logger.error("--input-dir is required for store mode")
            return 1

        from .db_storage import run_storage_mode
        result = run_storage_mode(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            db_path=args.db_path
        )

        if result != 0:
            overall_success = False

        logger.info("")  # Empty line for spacing

    # Mode 3: Query (search database)
    if query_mode:
        logger.info("="*60)
        logger.info("MODE 3: QUERY - Searching database")
        logger.info("="*60)

        from .query_mode import run_query_mode
        result = run_query_mode(
            query=args.query,
            output_dir=args.output_dir,
            db_path=args.db_path,
            limit=args.query_limit
        )

        if result != 0:
            overall_success = False

    # Final summary
    if scan_mode or store_mode:  # Only show summary if not just query mode
        logger.info("\n" + "="*60)
        logger.info("PIPELINE COMPLETE")
        logger.info("="*60)
        if overall_success:
            logger.info("All modes completed successfully")
            return 0
        else:
            logger.warning("Some modes encountered errors")
            return 1
    else:
        # Query mode only - exit code already handled by run_query_mode
        return 0 if overall_success else 1


if __name__ == '__main__':
    sys.exit(main())
