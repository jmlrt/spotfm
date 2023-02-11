import argparse
import logging
import os

from spotfm import lastfm


def recent_scrobbles(user, limit, scrobbles_minimum, period):
    scrobbles = user.get_recent_tracks_scrobbles(limit, scrobbles_minimum, period)
    for scrobble in scrobbles:
        print(scrobble)


def lastfm_cli(args):
    # You have to have your own unique two values for API_KEY and API_SECRET
    # Obtain yours from https://www.last.fm/api/account/create for Last.fm
    api_key = os.getenv("LASTFM_API_KEY")
    api_secret = os.getenv("LASTFM_API_SECRET")
    username = os.getenv("LASTFM_USERNAME")
    password_hash = os.getenv("LASTFM_PASSWORD_HASH")

    client = lastfm.Client(api_key, api_secret, username, password_hash)
    user = lastfm.User(client.client)

    match args.command:
        case "recent-scrobbles":
            recent_scrobbles(user, args.limit, args.scrobbles_minimum, args.period)


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
    args = parser.parse_args()

    match args.group:
        case "lastfm":
            lastfm_cli(args)


if __name__ == "__main__":
    main()
