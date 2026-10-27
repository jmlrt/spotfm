import argparse
import contextlib
import csv
import logging
import os
import shlex
import subprocess
import sys
import tempfile
from logging.handlers import RotatingFileHandler

from spotfm import lastfm, utils
from spotfm.lastfm import fetch_recent_scrobbles, read_lastfm_state, save_lastfm_state
from spotfm.spotify import client as spotify_client
from spotfm.spotify import constants as spotify_constants
from spotfm.spotify import dupes as spotify_dupes
from spotfm.spotify import misc as spotify_misc


def _positive_int(value):
    """Validate that a value is a positive integer."""
    ivalue = int(value)
    if ivalue <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return ivalue


def _non_negative_int(value):
    """Validate that a value is a non-negative integer."""
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"{value} is not a non-negative integer")
    return ivalue


def _format_track(track_dict):
    """Format a track dict as 'artist - title - period_scrobbles - total_scrobbles - url'."""
    return f"{track_dict['artist']} - {track_dict['title']} - {track_dict['period_scrobbles']} - {track_dict['total_scrobbles']} - {track_dict['url']}"


def _print_duplicate_ids(duplicates):
    """Print duplicate-ID results as CSV rows to stdout: playlists,artists,track."""
    writer = csv.writer(sys.stdout, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for dup in duplicates:
        writer.writerow([dup["playlists"], dup["artists"] or "", dup["track_name"]])


def _print_duplicate_names(duplicates):
    """Print fuzzy-matched pairs as CSV rows to stdout: playlists1,playlists2,artists1,artists2,track1,track2,score."""
    writer = csv.writer(sys.stdout, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    for dup in duplicates:
        writer.writerow(
            [
                dup["playlists1"],
                dup["playlists2"],
                dup["artists1"],
                dup["artists2"],
                dup["track1"],
                dup["track2"],
                f"{dup['score']:.2f}",
            ]
        )


def _rollback_lastfm_state(prev_count):
    """Restore the pre-fetch scrobble count so a retry re-fetches the same scrobbles."""
    if prev_count is not None:
        save_lastfm_state(prev_count)
    else:
        # First run: the fetch initialized the state file — remove it again
        with contextlib.suppress(OSError):
            lastfm.LASTFM_STATE_FILE.unlink(missing_ok=True)


def recent_scrobbles(user, limit, scrobbles_minimum, period, period_minimum, interactive, config):
    # Snapshot state before fetching: interactive mode rolls back to it on editor failure
    prev_state = read_lastfm_state()
    prev_count = prev_state.get("last_scrobble_count") if isinstance(prev_state, dict) else None
    is_first_run = prev_state is None

    # Fetch scrobbles with incremental state management (orchestration in lastfm module)
    tracks, mode = fetch_recent_scrobbles(
        user, config, limit=limit, scrobbles_minimum=scrobbles_minimum, period=period, period_minimum=period_minimum
    )

    # CLI-layer presentation: handle user feedback and interactive mode
    if mode == "no_new":
        print("No new scrobbles since last run.")
        return
    elif mode == "incremental":
        # prev_count is the pre-fetch snapshot; re-reading state now would return
        # the count this run just saved. Report the diff, clamped to the API cap.
        current_count = user.get_playcount()
        fetched = min(current_count - prev_count, lastfm.LASTFM_MAX_LIMIT)
        print(f"Fetching {fetched} new scrobbles (was {prev_count}, now {current_count}).")
    else:  # mode == "full"
        # First run shows initialization message; subsequent runs show fetch message
        effective_limit = limit if limit is not None else config.get("limit", 50)
        if is_first_run:
            print(f"Initializing scrobble tracking. Fetching up to {effective_limit} recent scrobbles.")
        else:
            print(f"Fetching {len(tracks)} recent scrobbles.")

    if not tracks:
        print("No results found.")
        return

    if interactive:
        lines = sorted({_format_track(s) for s in tracks})
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR", "vim")
        editor_args = shlex.split(editor)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
            tmp = f.name
        try:
            result = subprocess.run([*editor_args, tmp])
        finally:
            os.unlink(tmp)
        if result.returncode != 0:
            print(f"Editor command {' '.join(editor_args)} exited with status {result.returncode}.")
            _rollback_lastfm_state(prev_count)
            print("Last.FM state rolled back; fix the editor issue and retry.")
            return
    else:
        # Stream output in non-interactive mode
        for track in tracks:
            print(_format_track(track))


def count_tracks(playlists_pattern=None):
    results = spotify_misc.count_tracks(playlists_pattern)
    liked = spotify_misc.count_liked_tracks()
    print(f"tracks: {results}")
    print(f"liked tracks: {liked}")


def count_tracks_by_playlists():
    results = spotify_misc.count_tracks_by_playlists()
    for playlist, count in results:
        print(f"{playlist}: {count}")


def update_playlists(client, excluded_playlists, playlists_pattern=None, update_liked=True):
    client.update_playlists(excluded_playlists, playlists_pattern, update_liked=update_liked)


def lastfm_cli(args, config):
    client = lastfm.Client(
        config["lastfm"]["api_key"],
        config["lastfm"]["api_secret"],
        config["lastfm"]["username"],
        config["lastfm"]["password_hash"],
    )
    user = lastfm.User(client.client)

    match args.command:
        case "recent-scrobbles":
            # Use config default for scrobbles_minimum if not explicitly passed
            scrobbles_minimum = args.scrobbles_minimum
            if scrobbles_minimum is None:
                scrobbles_minimum = config.get("lastfm", {}).get("scrobbles_minimum", 4)

            # Use config default for period_minimum if not explicitly passed
            period_minimum = args.period_minimum
            if period_minimum is None:
                period_minimum = config.get("lastfm", {}).get("period_minimum")

            recent_scrobbles(
                user,
                args.limit,
                scrobbles_minimum,
                args.period,
                period_minimum,
                args.interactive,
                config.get("lastfm", {}),
            )


def spotify_cli(args, config):
    # Validate that --log-counts is only used with update-playlists
    if hasattr(args, "log_counts") and args.log_counts and args.command != "update-playlists":
        print("Error: --log-counts flag is only available for the 'update-playlists' command")
        raise SystemExit(1)

    client = spotify_client.Client(
        config["spotify"]["client_id"],
        config["spotify"]["client_secret"],
    )

    match args.command:
        case "count-tracks-by-playlists":
            count_tracks_by_playlists()
        case "count-tracks":
            count_tracks(args.playlists)
        case "update-playlists":
            update_playlists(
                client,
                config["spotify"]["excluded_playlists"],
                args.playlists,
                update_liked=config["spotify"].get("update_liked", True),
            )
            if hasattr(args, "log_counts") and args.log_counts:
                spotify_misc.log_track_counts(config)
        case "update-liked":
            spotify_misc.update_liked_tracks(client.client)
        case "add-tracks-from-file":
            spotify_misc.add_tracks_from_file(client, args.file)
        case "add-tracks-from-file-batch":
            spotify_misc.add_tracks_from_file_batch(client, args.file)
        case "remove-tracks-from-playlist":
            if not args.playlists or not args.file:
                print("Error: remove-tracks-from-playlist requires both -p/--playlists and -f/--file")
                return
            if len(args.playlists) != 1:
                print(f"Error: remove-tracks-from-playlist accepts exactly one playlist (got {len(args.playlists)})")
                return
            client_read_write = spotify_client.Client(
                config["spotify"]["client_id"],
                config["spotify"]["client_secret"],
                scope=spotify_constants.SCOPE,
            )
            spotify_misc.remove_tracks_from_file(client_read_write, args.playlists[0], args.file)
        case "discover-from-playlists":
            client_read_write = spotify_client.Client(
                config["spotify"]["client_id"],
                config["spotify"]["client_secret"],
                scope=spotify_constants.SCOPE,
            )
            spotify_misc.discover_from_playlists(
                client_read_write, config["spotify"]["discover_playlist"], config["spotify"]["sources_playlists"]
            )
        case "find-duplicate-ids":
            excluded = config["spotify"].get("excluded_playlists", [])
            duplicates = spotify_dupes.find_duplicate_ids(excluded_playlist_ids=excluded)
            _print_duplicate_ids(duplicates)
        case "find-duplicate-names":
            excluded = config["spotify"].get("excluded_playlists", [])
            threshold = args.threshold if hasattr(args, "threshold") else 95
            duplicates = spotify_dupes.find_duplicate_names(excluded_playlist_ids=excluded, threshold=threshold)
            _print_duplicate_names(duplicates)
        case "find-relinked-tracks":
            excluded = config["spotify"].get("excluded_playlists", [])
            relinked = spotify_misc.find_relinked_tracks(
                client.client, excluded_playlist_ids=excluded, output_file=args.output
            )
            if not args.output:
                for track in relinked:
                    print(
                        f"Relinked - {track['playlist_name']} - {track['original_track']} -> {track['replacement_track']} - {track['original_id']} - {track['replacement_id']}"
                    )
        case "list-playlists-with-track-counts":
            playlists = spotify_misc.list_playlists_with_track_counts()
            total_entries = 0
            for name, p_id, count in playlists:
                print(f"{name} ({p_id}): {count} tracks")
                total_entries += count
            print(f"TOTAL playlist entries: {total_entries}")
        case "find-tracks":
            tracks = spotify_misc.find_tracks_by_criteria(
                playlist_patterns=args.playlists,
                start_date=args.start_date,
                end_date=args.end_date,
                genre_pattern=args.genre,
                output_file=args.output,
            )
            if not args.output:  # Only print to console if no output file specified
                for track in tracks:
                    print(
                        f"{track['artist_names']} - {track['track_name']} - "
                        f"{track['album_name']} - {track['release_year']} - "
                        f"{track['artist_genres']}"
                    )
        case "find-liked-only":
            tracks = spotify_misc.find_liked_only_tracks(output_file=args.output)
            if not args.output:  # Only print to console if no output file specified
                for track in tracks:
                    print(
                        f"{track['artist_names']} - {track['track_name']} - "
                        f"{track['album_name']} - {track['release_year']} - "
                        f"{track['artist_genres']}"
                    )


def main():
    # Set root logger to INFO to pass messages through to the file handler (INFO level).
    # Raised to DEBUG after arg parsing only when -v/--verbose is set.
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Always-on audit log file (with fallback to console-only if filesystem unavailable)
    try:
        utils.WORK_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(utils.LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        root_logger.addHandler(file_handler)
    except (PermissionError, OSError) as e:
        # Filesystem issue (e.g. permission denied, read-only home) — fall back to console-only
        print(f"Warning: Could not create audit log at {utils.LOG_FILE}: {e}", file=sys.stderr)

    # Console handler (stderr) — level set based on flags after arg parsing
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    console_handler.setLevel(logging.WARNING)  # Default: only warnings/errors
    root_logger.addHandler(console_handler)

    parser = argparse.ArgumentParser(
        prog="spotfm",
    )
    parser.add_argument("--info", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(required=True, dest="group")

    lastfm_parser = subparsers.add_parser("lastfm")
    lastfm_parser.add_argument("command", choices=["recent-scrobbles"])
    lastfm_parser.add_argument(
        "-l",
        "--limit",
        default=None,
        type=_positive_int,
        help=(
            "Number of recent scrobbles to fetch, overriding incremental mode"
            " (default: config value or 50 on first run, all new scrobbles on subsequent runs)"
        ),
    )
    lastfm_parser.add_argument(
        "-s",
        "--scrobbles-minimum",
        default=None,
        type=_non_negative_int,
        help="Minimum total scrobbles to include in results (uses config value or 4 if not specified)",
    )
    lastfm_parser.add_argument(
        "-p",
        "--period",
        default=90,
        type=_positive_int,
        help="Period in days to count scrobbles within (default: 90)",
    )
    lastfm_parser.add_argument(
        "--period-minimum",
        default=None,
        type=_non_negative_int,
        help="Minimum scrobbles in the period window (default: unset, i.e. no filter)",
    )
    lastfm_parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Open results in $EDITOR (or vim) with deduplication",
    )

    spotify_parser = subparsers.add_parser("spotify")
    spotify_parser.add_argument(
        "command",
        choices=[
            "count-tracks",
            "count-tracks-by-playlists",
            "update-playlists",
            "add-tracks-from-file",
            "add-tracks-from-file-batch",
            "remove-tracks-from-playlist",
            "discover-from-playlists",
            "find-duplicate-ids",
            "find-duplicate-names",
            "find-relinked-tracks",
            "list-playlists-with-track-counts",
            "find-tracks",
            "find-liked-only",
            "update-liked",
        ],
    )
    spotify_parser.add_argument(
        "-p", "--playlists", nargs="+", help="Playlist ID(s) or name pattern(s) (use %% as wildcard for LIKE syntax)"
    )
    spotify_parser.add_argument("-f", "--file")
    spotify_parser.add_argument("-o", "--output", help="Output CSV file path (for find-tracks, find-relinked-tracks)")
    spotify_parser.add_argument("--start-date", help="Filter by album release start date (YYYY-MM-DD)")
    spotify_parser.add_argument("--end-date", help="Filter by album release end date (YYYY-MM-DD)")
    spotify_parser.add_argument("--genre", help="Filter by genre using a regex pattern")
    spotify_parser.add_argument(
        "-t", "--threshold", type=int, default=95, help="Similarity threshold for fuzzy matching (0-100, default 95)"
    )
    spotify_parser.add_argument(
        "--log-counts",
        action="store_true",
        help="Log track counts to CSV after update-playlists (configurable via spotfm.toml: track_counts_log, new_tracks_pattern)",
    )

    args = parser.parse_args()

    # Set console handler level based on flags
    console_handler.setLevel(logging.WARNING)  # Default
    if args.info:
        console_handler.setLevel(logging.INFO)
    if args.verbose:
        console_handler.setLevel(logging.DEBUG)
        root_logger.setLevel(logging.DEBUG)  # Enable debug records only when -v is set

    config = utils.parse_config()

    match args.group:
        case "lastfm":
            lastfm_cli(args, config)
        case "spotify":
            spotify_cli(args, config)


if __name__ == "__main__":
    main()
