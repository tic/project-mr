import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from rapidfuzz import fuzz

from .logger import setup_logger

logger = setup_logger(__name__)


class QueryModeError(Exception):
    """Exception raised when query operations fail."""
    pass


class QueryEngine:
    """Manages text similarity search across transcription segments."""

    def __init__(self, db_path: Path):
        """
        Initialize query engine with database connection.

        Args:
            db_path: Path to the SQLite database file

        Raises:
            QueryModeError: If database connection fails
        """
        self.db_path = db_path
        self.conn = None

        try:
            self.conn = sqlite3.connect(str(db_path))
            self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        except Exception as e:
            raise QueryModeError(f"Failed to connect to database: {e}")

    def ensure_fts5_table(self) -> None:
        """
        Ensure FTS5 table exists and is populated.

        If the table doesn't exist, creates it and rebuilds from segments.

        Raises:
            QueryModeError: If FTS5 setup fails
        """
        try:
            cursor = self.conn.cursor()

            # Check if FTS5 table exists
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='segments_fts'
            """)

            if not cursor.fetchone():
                logger.warning("FTS5 table not found, creating and rebuilding...")

                # Create FTS5 virtual table
                cursor.execute("""
                    CREATE VIRTUAL TABLE segments_fts USING fts5(
                        text,
                        content=segments,
                        content_rowid=id,
                        tokenize='porter unicode61'
                    )
                """)

                # Rebuild FTS5 index from existing segments
                cursor.execute("INSERT INTO segments_fts(segments_fts) VALUES('rebuild')")

                self.conn.commit()
                logger.info("FTS5 table created and populated")

        except Exception as e:
            raise QueryModeError(f"Failed to ensure FTS5 table: {e}")

    def search(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Execute hybrid FTS5 + fuzzy search with fallback for maximum coverage.

        Args:
            query: Search query text
            limit: Maximum number of results to return

        Returns:
            List of result dictionaries with scores and data

        Raises:
            QueryModeError: If search fails
        """
        try:
            # Step 1: Try FTS5 keyword search (fetch 10x limit for more fuzzy matching options)
            fetch_limit = max(limit * 10, 200)  # At least 200 candidates
            candidates = self._fts5_search(query, fetch_limit)

            logger.debug(f"FTS5 returned {len(candidates)} candidates")

            # Step 2: If FTS5 returns too few results, fall back to broader search
            if len(candidates) < limit * 2:
                logger.debug(f"FTS5 returned few results, adding fallback search")
                fallback_candidates = self._fallback_search(query, fetch_limit)
                # Merge with FTS5 results, avoiding duplicates
                seen_ids = {c['segment_id'] for c in candidates}
                for candidate in fallback_candidates:
                    if candidate['segment_id'] not in seen_ids:
                        candidates.append(candidate)
                        seen_ids.add(candidate['segment_id'])
                logger.debug(f"After fallback: {len(candidates)} total candidates")

            if not candidates:
                logger.info("No results found for query")
                return []

            # Step 3: Fuzzy re-ranking with multiple algorithms
            results = self._fuzzy_rerank(query, candidates, limit)

            logger.info(f"Returning {len(results)} results for query: {query}")
            return results

        except Exception as e:
            raise QueryModeError(f"Search failed: {e}")

    def _fts5_search(self, query: str, fetch_limit: int) -> List[Dict[str, Any]]:
        """
        Step 1: Fast keyword-based filtering using FTS5 with forgiving matching.

        Args:
            query: Search query text
            fetch_limit: Number of candidates to fetch

        Returns:
            List of candidate dictionaries from FTS5 search
        """
        cursor = self.conn.cursor()

        # Make FTS5 query more forgiving: OR between words, add wildcards
        # Split query into words and create OR query with wildcards
        words = query.strip().split()
        if len(words) > 1:
            # For multi-word queries: try exact phrase first, then OR with wildcards
            fts_query = f'"{query}" OR ' + ' OR '.join(f'{word}*' for word in words)
        else:
            # For single word: use wildcard
            fts_query = f'{query}*'

        try:
            # Execute FTS5 search with joined file information
            cursor.execute("""
                SELECT
                    s.id AS segment_id,
                    s.file_id,
                    s.segment_id AS segment_number,
                    s.start_time,
                    s.end_time,
                    s.text,
                    f.media_file,
                    f.media_filename,
                    f.duration_seconds,
                    f.model,
                    f.processed_at,
                    fts.rank AS fts_score
                FROM segments_fts fts
                JOIN segments s ON fts.rowid = s.id
                JOIN files f ON s.file_id = f.id
                WHERE segments_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (fts_query, fetch_limit))

            # Convert rows to dictionaries
            candidates = []
            for row in cursor.fetchall():
                candidates.append(dict(row))

            return candidates

        except Exception as e:
            logger.warning(f"FTS5 search failed with query '{fts_query}': {e}")
            # If FTS5 fails, return empty list (fallback will handle it)
            return []

    def _fallback_search(self, query: str, fetch_limit: int) -> List[Dict[str, Any]]:
        """
        Fallback search: retrieve segments for fuzzy matching when FTS5 returns few results.

        Retrieves a sample of segments from the database for fuzzy matching.

        Args:
            query: Search query text
            fetch_limit: Number of candidates to fetch

        Returns:
            List of candidate dictionaries
        """
        cursor = self.conn.cursor()

        try:
            # Get a diverse sample of segments
            # Use RANDOM() for sampling across different files
            cursor.execute("""
                SELECT
                    s.id AS segment_id,
                    s.file_id,
                    s.segment_id AS segment_number,
                    s.start_time,
                    s.end_time,
                    s.text,
                    f.media_file,
                    f.media_filename,
                    f.duration_seconds,
                    f.model,
                    f.processed_at,
                    0.0 AS fts_score
                FROM segments s
                JOIN files f ON s.file_id = f.id
                ORDER BY RANDOM()
                LIMIT ?
            """, (fetch_limit,))

            candidates = []
            for row in cursor.fetchall():
                candidates.append(dict(row))

            return candidates

        except Exception as e:
            logger.warning(f"Fallback search failed: {e}")
            return []

    def _fuzzy_rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        final_limit: int
    ) -> List[Dict[str, Any]]:
        """
        Step 2: Re-rank using multiple RapidFuzz fuzzy matching algorithms.

        Uses multiple fuzzy algorithms and takes the best score for maximum coverage.

        Args:
            query: Original search query
            candidates: List of candidates from FTS5 search
            final_limit: Final number of results to return

        Returns:
            Top N results sorted by combined score
        """
        scored_results = []

        # Normalize FTS5 BM25 scores (negative values, lower absolute = better)
        max_fts = max(abs(c['fts_score']) for c in candidates) if candidates else 1

        query_lower = query.lower()

        for candidate in candidates:
            text_lower = candidate['text'].lower()

            # Normalize FTS5 to 0-100 scale (invert negative BM25)
            fts_normalized = (abs(candidate['fts_score']) / max_fts) * 100

            # Calculate multiple fuzzy match scores for best coverage
            # 1. partial_ratio: substring matching (most forgiving)
            partial_score = fuzz.partial_ratio(query_lower, text_lower)

            # 2. token_sort_ratio: handles different word orders
            token_sort_score = fuzz.token_sort_ratio(query_lower, text_lower)

            # 3. token_set_ratio: handles different word sets
            token_set_score = fuzz.token_set_ratio(query_lower, text_lower)

            # 4. WRatio: weighted ratio (overall best match)
            wratio_score = fuzz.WRatio(query_lower, text_lower)

            # Take the MAXIMUM fuzzy score across all algorithms
            # This makes matching more forgiving - if any algorithm finds similarity, we use it
            fuzzy_score = max(partial_score, token_sort_score, token_set_score, wratio_score)

            # Combined score: FTS 30%, Fuzzy 70%
            # Weight fuzzy even higher for maximum coverage
            combined_score = (fts_normalized * 0.3) + (fuzzy_score * 0.7)

            # Build result dictionary with detailed scores
            result = {
                'score': round(combined_score, 2),
                'fts_score': candidate['fts_score'],
                'fuzzy_score': fuzzy_score,
                'fuzzy_details': {
                    'partial_ratio': partial_score,
                    'token_sort_ratio': token_sort_score,
                    'token_set_ratio': token_set_score,
                    'wratio': wratio_score
                },
                'segment': {
                    'id': candidate['segment_id'],
                    'segment_number': candidate['segment_number'],
                    'start_time': candidate['start_time'],
                    'end_time': candidate['end_time'],
                    'text': candidate['text']
                },
                'file': {
                    'media_file': candidate['media_file'],
                    'media_filename': candidate['media_filename'],
                    'duration_seconds': candidate['duration_seconds'],
                    'model': candidate['model'],
                    'processed_at': candidate['processed_at']
                }
            }

            scored_results.append(result)

        # Sort by combined score descending
        scored_results.sort(key=lambda x: x['score'], reverse=True)

        # Return top N results
        return scored_results[:final_limit]

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __del__(self):
        """Cleanup database connection on object destruction."""
        self.close()


def run_query_mode(
    query: str,
    output_dir: Optional[str] = None,
    db_path: Optional[str] = None,
    limit: int = 50
) -> int:
    """
    Run QuoteFinder in query mode to search for similar segments.

    Args:
        query: Search query text
        output_dir: Output directory (used to find default database path)
        db_path: Explicit path to SQLite database file
        limit: Maximum number of results to return

    Returns:
        0 if successful, 1 if error occurred
    """
    # 1. Validate query
    if not query or not query.strip():
        logger.error("Query cannot be empty")
        return 1

    # 2. Resolve database path
    if db_path is None:
        if output_dir is None:
            logger.error("Must specify --output-dir or --db-path for query mode")
            return 1
        db_file_path = Path(output_dir) / "sqlite" / "quotefinder.db"
    else:
        db_file_path = Path(db_path)

    # 3. Check database exists
    if not db_file_path.exists():
        logger.error(f"Database not found: {db_file_path}")
        logger.error("Run with --storage-mode first to create database")
        return 1

    logger.info("QuoteFinder - Query Mode")
    logger.info(f"Database: {db_file_path}")
    logger.info(f"Query: {query}")
    logger.info(f"Limit: {limit}\n")

    # 4. Initialize query engine
    engine = None
    try:
        engine = QueryEngine(db_file_path)
        engine.ensure_fts5_table()
    except QueryModeError as e:
        logger.error(f"Failed to initialize query engine: {e}")
        return 1

    # 5. Execute search
    try:
        results = engine.search(query, limit)

        # Build output JSON
        output = {
            "query": query,
            "result_count": len(results),
            "total_candidates": len(results) if len(results) < limit else limit * 3,
            "results": results
        }

        # Output to stdout
        print(json.dumps(output, indent=2, ensure_ascii=False))

    except QueryModeError as e:
        logger.error(f"Search failed: {e}")
        return 1

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1

    finally:
        if engine:
            engine.close()

    return 0
