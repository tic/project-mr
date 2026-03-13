import sqlite3
from pathlib import Path
from typing import Optional

from .logger import setup_logger
from .storage import load_transcription, StorageError

logger = setup_logger(__name__)


class DatabaseError(Exception):
    """Exception raised when database operations fail."""
    pass


class DatabaseManager:
    """Manages SQLite database operations for QuoteFinder transcriptions."""

    def __init__(self, db_path: Path):
        """
        Initialize the database manager.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.conn = None

    def init_database(self) -> None:
        """
        Initialize database connection and create tables.

        Raises:
            DatabaseError: If database initialization fails
        """
        try:
            # Create parent directories if they don't exist
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            # Connect to database
            self.conn = sqlite3.connect(str(self.db_path))

            # Enable foreign key constraints
            self.conn.execute("PRAGMA foreign_keys = ON")

            # Create tables and indexes
            self._create_tables()

            logger.info(f"Database initialized: {self.db_path}")

        except Exception as e:
            raise DatabaseError(f"Failed to initialize database: {e}")

    def _create_tables(self) -> None:
        """Create database tables and indexes."""
        cursor = self.conn.cursor()

        # Create files table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                media_file TEXT NOT NULL UNIQUE,
                media_filename TEXT NOT NULL,
                processed_at TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                model TEXT NOT NULL,
                total_segments INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create segments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                segment_id INTEGER NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                text TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            )
        """)

        # Create indexes for files table
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_media_file
            ON files(media_file)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_media_filename
            ON files(media_filename)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_files_processed_at
            ON files(processed_at)
        """)

        # Create indexes for segments table
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_file_id
            ON segments(file_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_start_time
            ON segments(start_time)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_text
            ON segments(text)
        """)

        # Create FTS5 virtual table for full-text search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                text,
                content=segments,
                content_rowid=id,
                tokenize='porter unicode61'
            )
        """)

        # Create triggers to keep FTS5 in sync with segments table
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
                INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, text)
                VALUES('delete', old.id, old.text);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
                INSERT INTO segments_fts(segments_fts, rowid, text)
                VALUES('delete', old.id, old.text);
                INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
            END
        """)

        self.conn.commit()

    def load_json_to_db(self, json_path: Path) -> bool:
        """
        Load a JSON transcription file into the database.

        Args:
            json_path: Path to the JSON file

        Returns:
            True if this was an update (replaced existing), False if new insert

        Raises:
            DatabaseError: If loading fails
        """
        try:
            # Load JSON using existing storage module
            data = load_transcription(json_path)

            # Validate required fields
            required_fields = ['media_file', 'media_filename', 'processed_at',
                              'duration_seconds', 'segments']
            missing = [f for f in required_fields if f not in data]
            if missing:
                raise DatabaseError(f"Missing required fields: {missing}")

            # Get optional fields with defaults
            model = data.get('model', 'unknown')
            total_segments = data.get('total_segments', len(data['segments']))

            cursor = self.conn.cursor()
            was_update = False

            # Check if file already exists
            cursor.execute(
                "SELECT id FROM files WHERE media_file = ?",
                (data['media_file'],)
            )
            existing = cursor.fetchone()

            if existing:
                file_id = existing[0]
                was_update = True

                logger.debug(f"Updating existing record for: {data['media_file']}")

                # Delete existing segments (CASCADE will handle this, but being explicit)
                cursor.execute("DELETE FROM segments WHERE file_id = ?", (file_id,))

                # Delete file record
                cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))

            # Insert file record
            cursor.execute("""
                INSERT INTO files (
                    media_file, media_filename, processed_at,
                    duration_seconds, model, total_segments
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                data['media_file'],
                data['media_filename'],
                data['processed_at'],
                data['duration_seconds'],
                model,
                total_segments
            ))

            file_id = cursor.lastrowid

            # Insert segments
            segments = data['segments']
            for segment in segments:
                cursor.execute("""
                    INSERT INTO segments (
                        file_id, segment_id, start_time, end_time, text
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    file_id,
                    segment['id'],
                    segment['start'],
                    segment['end'],
                    segment['text']
                ))

            self.conn.commit()
            return was_update

        except StorageError as e:
            # Re-raise storage errors from load_transcription
            if self.conn:
                self.conn.rollback()
            raise DatabaseError(f"Failed to load {json_path.name}: {e}")
        except Exception as e:
            if self.conn:
                self.conn.rollback()
            raise DatabaseError(f"Failed to load {json_path.name}: {e}")

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self):
        """Close database connection on cleanup."""
        self.close()


def run_storage_mode(
    input_dir: str,
    output_dir: Optional[str] = None,
    db_path: Optional[str] = None
) -> int:
    """
    Run QuoteFinder in storage mode to load JSON files into SQLite database.

    Args:
        input_dir: Input directory (used if output_dir is None)
        output_dir: Directory containing JSON files (defaults to input_dir)
        db_path: Path to SQLite database file (defaults to quotefinder.db in output_dir)

    Returns:
        0 if successful, 1 if any failures occurred
    """
    # Determine output directory
    if output_dir is None:
        output_dir = input_dir

    output_path = Path(output_dir)

    # JSON files are in /json subdirectory
    json_path = output_path / "json"

    # Database goes in /sqlite subdirectory
    if db_path is None:
        db_file_path = output_path / "sqlite" / "quotefinder.db"
    else:
        db_file_path = Path(db_path)

    logger.info("QuoteFinder - Storage Mode")
    logger.info(f"Loading JSON files from: {json_path}")
    logger.info(f"Database: {db_file_path}")

    # Initialize database
    db_manager = None
    try:
        db_manager = DatabaseManager(db_file_path)
        db_manager.init_database()
    except DatabaseError as e:
        logger.error(f"Failed to initialize database: {e}")
        return 1

    # Scan for JSON files in /json subdirectory
    if not json_path.exists():
        logger.warning(f"JSON directory does not exist: {json_path}")
        if db_manager:
            db_manager.close()
        return 0

    json_files = list(json_path.glob("*.json"))

    if not json_files:
        logger.warning(f"No JSON files found in {json_path}")
        if db_manager:
            db_manager.close()
        return 0

    logger.info(f"Found {len(json_files)} JSON file(s) to process\n")

    # Process each file
    success_count = 0
    failure_count = 0
    update_count = 0

    try:
        for i, json_file in enumerate(json_files, 1):
            try:
                logger.info(f"[{i}/{len(json_files)}] Processing: {json_file.name}")
                was_update = db_manager.load_json_to_db(json_file)

                if was_update:
                    update_count += 1
                    logger.info(f"  ✓ Updated existing record")
                else:
                    logger.info(f"  ✓ Loaded successfully")

                success_count += 1

            except DatabaseError as e:
                logger.error(f"  ✗ Failed to load {json_file.name}: {e}")
                failure_count += 1

    except KeyboardInterrupt:
        logger.warning("\n\nStorage mode interrupted by user")
        if db_manager:
            db_manager.close()
        return 1

    finally:
        # Close database connection
        if db_manager:
            db_manager.close()

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("Storage Mode Summary")
        logger.info(f"{'='*60}")
        logger.info(f"Successfully loaded: {success_count}")
        logger.info(f"Updates (replaced existing): {update_count}")
        logger.info(f"Failed: {failure_count}")
        logger.info(f"Total: {success_count + failure_count}")

    return 0 if failure_count == 0 else 1
