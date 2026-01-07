import atexit
import logging
import sqlite3
import time

from spotfm import utils

# Global variables for the database connection
_db_connection = None
_current_database = None


# Dynamic attributes to always reference utils values (important for test monkeypatching)
def __getattr__(name):
    if name == "DATABASE":
        return utils.DATABASE
    elif name == "DATABASE_LOG_LEVEL":
        return utils.DATABASE_LOG_LEVEL
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db_connection(database):
    global _db_connection, _current_database
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
