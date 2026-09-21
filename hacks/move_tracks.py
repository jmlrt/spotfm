#!/usr/bin/env python3
"""Move tracks between Spotify playlists, sorted by artist then album name."""

import argparse
import logging
import re
import sys

from spotfm import utils
from spotfm.spotify import client as spotify_client
from spotfm.spotify import constants as spotify_constants
from spotfm.spotify import playlist as playlist_module
from spotfm.spotify.misc import resolve_playlist_patterns_to_ids

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_playlist_identifier(identifier: str) -> str:
    """Extract playlist ID from Spotify URL or pass through bare ID/name.

    Args:
        identifier: Spotify playlist URL, 22-char ID, or playlist name

    Returns:
        22-char playlist ID or playlist name
    """
    match = re.search(r"playlist/([A-Za-z0-9]{22})", identifier)
    if match:
        return match.group(1)
    return identifier


def resolve_identifier(identifier: str, label: str) -> str:
    """Resolve playlist identifier to 22-char ID.

    Args:
        identifier: URL, 22-char ID, or playlist name
        label: Label for error messages

    Returns:
        22-char playlist ID

    Raises:
        SystemExit: If playlist not found
    """
    parsed = parse_playlist_identifier(identifier)

    if len(parsed) == 22 and parsed.isalnum():
        logger.debug(f"{label} resolved to ID: {parsed}")
        return parsed

    resolved = resolve_playlist_patterns_to_ids(parsed)
    resolved_ids = resolved[0] if isinstance(resolved, tuple) else resolved

    if not resolved_ids:
        logger.error(f"{label} playlist not found: {identifier}")
        sys.exit(1)

    resolved_id: str = resolved_ids[0]
    logger.debug(f"{label} '{parsed}' resolved to ID: {resolved_id}")
    return resolved_id


def move_tracks(
    client: spotify_client.Client,
    source_id: str,
    dest_id: str,
    count: int,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[str]:
    """Move tracks from source to destination playlist, sorted by artist then album.

    Args:
        client: Spotify client with write permissions
        source_id: Source playlist ID
        dest_id: Destination playlist ID
        count: Number of tracks to move
        dry_run: If True, only show what would be moved without modifying playlists
        verbose: If True, show detailed logging; if False and dry_run, only show track list

    Returns:
        List of track IDs that were moved
    """
    quiet = dry_run and not verbose

    if not quiet:
        logger.info("Running pre-flight playlist updates...")
    client.update_playlists(playlists_patterns=[source_id])
    client.update_playlists(playlists_patterns=[dest_id])

    if not quiet:
        logger.info(f"Loading source playlist {source_id}...")
    source = playlist_module.Playlist.get_playlist(source_id, client.client, refresh=False)
    if not quiet:
        if source.tracks:
            logger.info(f"Loaded {len(source.tracks)} tracks from source playlist")
        else:
            logger.info("Loaded 0 tracks from source playlist")

    if not quiet:
        logger.info("Sorting tracks by artist then album...")

    def sort_key(track):
        artist = track.artists[0].name.lower() if track.artists else ""
        album = track.album.lower() if track.album else ""
        return (artist, album)

    sorted_tracks = sorted(source.tracks, key=sort_key) if source.tracks else []
    tracks_to_move = sorted_tracks[:count]
    track_ids = [t.id for t in tracks_to_move]

    if quiet:
        for i, track in enumerate(tracks_to_move, 1):
            artist = track.artists[0].name if track.artists else "Unknown"
            album = track.album or "Unknown"
            print(f"{i:2d}. {artist} - {album} - {track.name}")
    else:
        logger.info(f"Selected {len(tracks_to_move)} tracks to move:")
        for i, track in enumerate(tracks_to_move, 1):
            artist = track.artists[0].name if track.artists else "Unknown"
            album = track.album or "Unknown"
            logger.info(f"  {i:2d}. {artist} - {album} - {track.name}")

    if dry_run:
        if not quiet:
            logger.info("DRY RUN: No changes made")
        return track_ids

    logger.info(f"Adding {len(tracks_to_move)} tracks to destination playlist...")
    dest = playlist_module.Playlist.get_playlist(dest_id, client.client, refresh=False)
    dest.add_tracks(tracks_to_move, client.client)

    logger.info(f"Removing {len(tracks_to_move)} tracks from source playlist...")
    source.remove_tracks(track_ids, client.client)

    logger.info("Running post-operation playlist updates...")
    client.update_playlists(playlists_patterns=[source_id])
    client.update_playlists(playlists_patterns=[dest_id])

    logger.info(f"Successfully moved {len(track_ids)} tracks")
    return track_ids


def main() -> None:
    """Parse arguments and execute move_tracks."""
    parser = argparse.ArgumentParser(description="Move tracks between Spotify playlists, sorted by artist then album")
    parser.add_argument("-s", "--source", required=True, help="Source playlist ID, URL, or name")
    parser.add_argument("-d", "--dest", required=True, help="Destination playlist ID, URL, or name")
    parser.add_argument("-n", "--count", type=int, required=True, help="Number of tracks to move")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be moved without making changes")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    source_id = resolve_identifier(args.source, "Source")
    dest_id = resolve_identifier(args.dest, "Destination")

    if source_id == dest_id:
        logger.error("Source and destination playlists must be different")
        sys.exit(1)

    config = utils.parse_config()
    client = spotify_client.Client(
        config["spotify"]["client_id"],
        config["spotify"]["client_secret"],
        scope=spotify_constants.SCOPE,
    )

    move_tracks(client, source_id, dest_id, args.count, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
