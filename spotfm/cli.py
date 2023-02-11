import argparse
import logging

from spotfm import lastfm, spotify, utils


def recent_scrobbles(user, limit, scrobbles_minimum, period):
    scrobbles = user.get_recent_tracks_scrobbles(limit, scrobbles_minimum, period)
    for scrobble in scrobbles:
        print(scrobble)


def count_tracks(client):
    spotify.count_tracks_in_playlists(client.client)


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
    client = spotify.Client(
        config["spotify"]["client_id"],
        config["spotify"]["client_secret"],
    )

    match args.command:
        case "count-tracks":
            count_tracks(client)


def main():
    logging.basicConfig()

    parser = argparse.ArgumentParser(
        prog="spotfm",
    )
    subparsers = parser.add_subparsers(required=True, dest="group")
    lastfm_parser = subparsers.add_parser("lastfm")
    lastfm_parser.add_argument("command", choices=["recent-scrobbles"])
    lastfm_parser.add_argument("-l", "--limit", default=50, type=int)
    lastfm_parser.add_argument("-s", "--scrobbles-minimum", default=4, type=int)
    lastfm_parser.add_argument("-p", "--period", default=90, type=int)
    spotify_parser = subparsers.add_parser("spotify")
    spotify_parser.add_argument("command", choices=["count-tracks"])
    args = parser.parse_args()

    config = utils.parse_config()

    match args.group:
        case "lastfm":
            lastfm_cli(args, config)
        case "spotify":
            spotify_cli(args, config)


if __name__ == "__main__":
    main()
