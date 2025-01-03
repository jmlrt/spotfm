import argparse
import logging

from spotfm import lastfm, utils
from spotfm.spotify import client as spotify_client
from spotfm.spotify import misc as spotify_misc


def recent_scrobbles(user, limit, scrobbles_minimum, period):
    scrobbles = user.get_recent_tracks_scrobbles(limit, scrobbles_minimum, period)
    for scrobble in scrobbles:
        print(scrobble)


def count_tracks(playlists_pattern=None):
    results = spotify_misc.count_tracks(playlists_pattern)
    print(results)


def count_tracks_by_playlists():
    results = spotify_misc.count_tracks_by_playlists()
    for playlist, count in results:
        print(f"{playlist}: {count}")


def update_playlists(client, excluded_playlists):
    client.update_playlists(excluded_playlists)


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
            recent_scrobbles(user, args.limit, args.scrobbles_minimum, args.period)


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
            update_playlists(client, config["spotify"]["excluded_playlists"])
        case "add-tracks-from-file":
            spotify_misc.add_tracks_from_file(client, args.file)
        case "add-tracks-from-file-batch":
            spotify_misc.add_tracks_from_file_batch(client, args.file)
        case "discover-from-playlists":
            spotify_misc.discover_from_playlists(
                client, config["spotify"]["discover_playlist"], config["spotify"]["sources_playlists"]
            )


def main():
    logging.basicConfig()

    parser = argparse.ArgumentParser(
        prog="spotfm",
    )
    parser.add_argument("-i", "--info", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    subparsers = parser.add_subparsers(required=True, dest="group")

    lastfm_parser = subparsers.add_parser("lastfm")
    lastfm_parser.add_argument("command", choices=["recent-scrobbles"])
    lastfm_parser.add_argument("-l", "--limit", default=50, type=int)
    lastfm_parser.add_argument("-s", "--scrobbles-minimum", default=4, type=int)
    lastfm_parser.add_argument("-p", "--period", default=90, type=int)

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
        ],
    )
    spotify_parser.add_argument("-p", "--playlists")
    spotify_parser.add_argument("-f", "--file")

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
