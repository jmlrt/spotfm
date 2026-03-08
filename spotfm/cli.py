import argparse
import logging
import os
import subprocess
import tempfile

from spotfm import lastfm, utils
from spotfm.lastfm import read_lastfm_state, save_lastfm_state
from spotfm.spotify import client as spotify_client
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


def recent_scrobbles(user, limit, scrobbles_minimum, period, period_minimum, interactive):
    current_count = user.get_playcount()
    scrobble_count_to_save = current_count  # Track what state to save

    state = read_lastfm_state()
    if state is None:
        # First run: initialize state with current count, fetch --limit scrobbles
        print(f"Initializing scrobble tracking. Fetching up to {limit} recent scrobbles.")
        save_lastfm_state(current_count)
    else:
        # Subsequent runs: fetch all new scrobbles since last run
        last_scrobble_count = None
        if isinstance(state, dict):
            last_scrobble_count = state.get("last_scrobble_count")
        if not isinstance(last_scrobble_count, int):
            print("Invalid previous state. Re-initializing scrobble tracking.")
            save_lastfm_state(current_count)
            return
        computed_limit = current_count - last_scrobble_count
        if computed_limit <= 0:
            print("No new scrobbles since last run.")
            save_lastfm_state(current_count)
            return
        # Fetch all new scrobbles on subsequent runs
        limit = computed_limit
        print(f"Fetching {limit} new scrobbles (was {last_scrobble_count}, now {current_count}).")

    # Collect all results first so exceptions/logs surface before editor opens
    scrobbles = list(user.get_recent_tracks_scrobbles(limit, scrobbles_minimum, period, period_minimum))

    if interactive:
        lines = sorted(set(scrobbles))
        if not lines:
            print("No results to open in editor.")
            save_lastfm_state(scrobble_count_to_save)
            return

        editor = os.environ.get("EDITOR", "vim")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n".join(lines))
            tmp = f.name
        try:
            subprocess.run([editor, tmp])
        finally:
            os.unlink(tmp)
    else:
        for scrobble in scrobbles:
            print(scrobble)

    save_lastfm_state(scrobble_count_to_save)


def count_tracks(playlists_pattern=None):
    results = spotify_misc.count_tracks(playlists_pattern)
    print(results)


def count_tracks_by_playlists():
    results = spotify_misc.count_tracks_by_playlists()
    for playlist, count in results:
        print(f"{playlist}: {count}")


def update_playlists(client, excluded_playlists, playlists_pattern=None):
    client.update_playlists(excluded_playlists, playlists_pattern)


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

            recent_scrobbles(user, args.limit, scrobbles_minimum, args.period, period_minimum, args.interactive)


def spotify_cli(args, config):
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
            update_playlists(client, config["spotify"]["excluded_playlists"], args.playlists)
        case "add-tracks-from-file":
            spotify_misc.add_tracks_from_file(client, args.file)
        case "add-tracks-from-file-batch":
            spotify_misc.add_tracks_from_file_batch(client, args.file)
        case "discover-from-playlists":
            client_read_write = spotify_client.Client(
                config["spotify"]["client_id"],
                config["spotify"]["client_secret"],
                scope="playlist-modify-private",
            )
            spotify_misc.discover_from_playlists(
                client_read_write, config["spotify"]["discover_playlist"], config["spotify"]["sources_playlists"]
            )
        case "find-duplicate-ids":
            excluded = config["spotify"].get("excluded_playlists", [])
            spotify_dupes.find_duplicate_ids(excluded_playlist_ids=excluded, output_file=args.output)
        case "find-duplicate-names":
            excluded = config["spotify"].get("excluded_playlists", [])
            threshold = args.threshold if hasattr(args, "threshold") else 95
            spotify_dupes.find_duplicate_names(
                excluded_playlist_ids=excluded, output_file=args.output, threshold=threshold
            )
        case "find-relinked-tracks":
            excluded = config["spotify"].get("excluded_playlists", [])
            spotify_misc.find_relinked_tracks(client.client, excluded_playlist_ids=excluded, output_file=args.output)
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


def main():
    logging.basicConfig()

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
        default=50,
        type=_positive_int,
        help="Number of recent scrobbles to fetch (default: 50 on first run; on subsequent runs, fetches all new scrobbles unless capped with --limit)",
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
        help="Minimum scrobbles in the period window (default: 1, i.e. no filter)",
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
            "discover-from-playlists",
            "find-duplicate-ids",
            "find-duplicate-names",
            "find-relinked-tracks",
            "list-playlists-with-track-counts",
            "find-tracks",
        ],
    )
    spotify_parser.add_argument(
        "-p", "--playlists", nargs="+", help="Playlist ID(s) or name pattern(s) (use %% as wildcard for LIKE syntax)"
    )
    spotify_parser.add_argument("-f", "--file")
    spotify_parser.add_argument("-o", "--output", help="Output CSV file path")
    spotify_parser.add_argument("--start-date", help="Filter by album release start date (YYYY-MM-DD)")
    spotify_parser.add_argument("--end-date", help="Filter by album release end date (YYYY-MM-DD)")
    spotify_parser.add_argument("--genre", help="Filter by genre using a regex pattern")
    spotify_parser.add_argument(
        "-t", "--threshold", type=int, default=95, help="Similarity threshold for fuzzy matching (0-100, default 95)"
    )

    args = parser.parse_args()

    if args.info:
        logging.getLogger().setLevel(logging.INFO)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = utils.parse_config()

    match args.group:
        case "lastfm":
            lastfm_cli(args, config)
        case "spotify":
            spotify_cli(args, config)


if __name__ == "__main__":
    main()
