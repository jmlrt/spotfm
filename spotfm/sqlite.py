import atexit
import logging
import sqlite3
import time

from spotfm import utils

# Global variables for the database connection
_db_connection = None
_current_database = None
_migration_completed = False


# Dynamic attributes to always reference utils values (important for test monkeypatching)
def __getattr__(name):
    if name == "DATABASE":
        return utils.DATABASE
    elif name == "DATABASE_LOG_LEVEL":
        return utils.DATABASE_LOG_LEVEL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def migrate_database_schema(database=None):
    """Migrate database schema to latest version.

    This function is called automatically on first connection to ensure
    the database schema is up-to-date. It's idempotent and safe to run
    multiple times.

    Args:
        database: Path to database (defaults to utils.DATABASE)
    """
    global _migration_completed

    # Skip if already migrated in this session
    if _migration_completed:
        return

    if database is None:
        database = utils.DATABASE

    logging.info("Checking database schema version...")

    try:
        conn = sqlite3.connect(str(database))
        cursor = conn.cursor()

        # Check if lifecycle columns exist
        try:
            cursor.execute("SELECT created_at FROM tracks LIMIT 1")
            logging.info("Database schema is up-to-date")
            conn.close()
            _migration_completed = True
            return
        except sqlite3.OperationalError:
            logging.info("Migrating database schema to add lifecycle tracking...")

        # Add lifecycle columns
        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN created_at TEXT")
            logging.info("Added created_at column to tracks table")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

        try:
            cursor.execute("ALTER TABLE tracks ADD COLUMN last_seen_at TEXT")
            logging.info("Added last_seen_at column to tracks table")
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                raise

        # Backfill data for existing tracks
        logging.info("Backfilling lifecycle data for existing tracks...")

        # Strategy for last_seen_at:
        # - Tracks currently in playlists: set to current date (they are "seen" right now)
        # - Orphaned tracks: use their MAX(added_at) as proxy (when they were last in a playlist)
        cursor.execute("""
            UPDATE tracks
            SET last_seen_at = (
                CASE
                    WHEN EXISTS (SELECT 1 FROM playlists_tracks WHERE track_id = tracks.id)
                        THEN date('now')  -- Track is currently in a playlist
                    ELSE (
                        SELECT MAX(added_at) FROM playlists_tracks WHERE track_id = tracks.id
                    )  -- Orphaned: use last known playlist date
                END
            )
            WHERE last_seen_at IS NULL
        """)

        # Strategy for created_at:
        # - Use MIN(added_at) from playlists_tracks as best guess for first discovery
        # - For truly orphaned tracks with no history: use current date
        cursor.execute("""
            UPDATE tracks
            SET created_at = COALESCE(
                (SELECT MIN(added_at) FROM playlists_tracks WHERE track_id = tracks.id),
                last_seen_at,
                date('now')
            )
            WHERE created_at IS NULL
        """)

        rows_updated = cursor.rowcount
        logging.info(f"Backfilled lifecycle data for {rows_updated} tracks")

        conn.commit()
        conn.close()

        logging.info("Database migration completed successfully")
        _migration_completed = True

    except Exception as e:
        logging.error(f"Database migration failed: {e}")
        # Don't prevent application from running if migration fails
        # The code has fallbacks for missing columns
        _migration_completed = True  # Mark as attempted to avoid retry loops


def get_db_connection(database):
    global _db_connection, _current_database
    # Run migration on first connection
    migrate_database_schema(database)
    # Convert to string for consistent comparison
    database_str = str(database)
    # If database changed or no connection exists, create new connection
    if _db_connection is None or _current_database != database_str:
        # Close existing connection if it exists
        if _db_connection is not None:
            _db_connection.close()
        _db_connection = sqlite3.connect(database)
        _db_connection.set_trace_callback(utils.DATABASE_LOG_LEVEL)
        _current_database = database_str
    return _db_connection


def close_db_connection():
    global _db_connection, _current_database
    if _db_connection is not None:
        logging.debug("Closing database connection")
        _db_connection.close()
        _db_connection = None
        _current_database = None


# Register the cleanup function globally
atexit.register(close_db_connection)


def query_db(database, queries, script=False, results=False):
    con = get_db_connection(database)
    cur = con.cursor()
    for query in queries:
        if script:
            cur.executescript(query)
        else:
            cur.execute(query)
    if results:
        query_results = cur.fetchall()
    con.commit()
    # spare CPU load
    time.sleep(0.01)
    if results:
        return query_results


def select_db(database, query, params=""):
    con = get_db_connection(database)
    cur = con.cursor()
    res = cur.execute(query, params)
    return res


def query_db_select(database, query, params=""):
    """Execute SELECT query and return results with automatic cleanup.

    Preferred method for SELECT queries - properly manages connections.

    Args:
        database: Path to SQLite database
        query: SQL SELECT query
        params: Query parameters (tuple or empty string)

    Returns:
        List of result rows
    """
    con = get_db_connection(database)
    cur = con.cursor()
    cur.execute(query, params if params else ())
    results = cur.fetchall()
    return results
