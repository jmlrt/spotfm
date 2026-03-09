#!/usr/bin/env python3
"""One-off script: remove IR-Backlog-Mar-9 tracks that duplicate tracks in other playlists.

Reads dupes.csv (output of `spfm spotify find-duplicate-names`) and removes tracks
from IR-Backlog-Mar-9 where:
- Exactly one side of the match is IR-Backlog-Mar-9
- The track titles are identical (not original vs. remix — those are intentional)

Run from repo root:
  python hacks/remove_backlog_dupes.py [--dry-run] [--csv dupes.csv]
"""

import argparse
import csv
import logging
import sys

BACKLOG_ID = "3qJuoBKFatWNl0XmO6iG0g"


def main():
    parser = argparse.ArgumentParser(description="Remove IR-Backlog-Mar-9 name-dupes from Spotify")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be removed, don't call API")
    parser.add_argument("--csv", default="dupes.csv", help="Path to dupes.csv (default: dupes.csv)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Import here so the script can still parse args without a full env
    from spotfm import sqlite, utils
    from spotfm.spotify import client as spotify_client
    from spotfm.spotify.playlist import Playlist

    # Parse dupes.csv — collect backlog track IDs for rows with identical titles
    track_ids_to_remove = set()
    skipped_title_mismatch = []

    with open(args.csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            pl1 = row["Playlists 1"]
            pl2 = row["Playlists 2"]
            title1 = row["Title 1"].strip()
            title2 = row["Title 2"].strip()
            artists1 = row["Artist 1"].strip()

            in_backlog_1 = BACKLOG_ID in pl1
            in_backlog_2 = BACKLOG_ID in pl2

            # Skip rows where both or neither side is the backlog
            if in_backlog_1 == in_backlog_2:
                continue

            # Only remove when titles are identical — skip original vs. remix pairs
            if title1.lower() != title2.lower():
                skipped_title_mismatch.append(f"{artists1} - {title1} / {title2}")
                continue

            backlog_title = title1 if in_backlog_1 else title2

            # Look up the track ID(s) in the backlog by title
            rows = sqlite.query_db_select(
                sqlite.DATABASE,
                "SELECT t.id FROM tracks t JOIN playlists_tracks pt ON t.id = pt.track_id WHERE pt.playlist_id = ? AND t.name = ?",
                (BACKLOG_ID, backlog_title),
            )
            for (track_id,) in rows:
                track_ids_to_remove.add(track_id)

    print(f"\nSkipped {len(skipped_title_mismatch)} rows (title mismatch = original vs. remix/version):")
    for s in skipped_title_mismatch[:10]:
        print(f"  {s}")
    if len(skipped_title_mismatch) > 10:
        print(f"  ... and {len(skipped_title_mismatch) - 10} more")

    if not track_ids_to_remove:
        print("\nNo tracks to remove.")
        return

    print(f"\n{len(track_ids_to_remove)} tracks to remove from IR-Backlog-Mar-9:")
    # Show track names for confirmation
    for track_id in sorted(track_ids_to_remove):
        name_rows = sqlite.query_db_select(sqlite.DATABASE, "SELECT name FROM tracks WHERE id = ?", (track_id,))
        name = name_rows[0][0] if name_rows else track_id
        print(f"  {track_id}  {name}")

    if args.dry_run:
        print("\n[dry-run] Not removing anything.")
        return

    confirm = input(f"\nRemove these {len(track_ids_to_remove)} tracks from IR-Backlog-Mar-9? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    config = utils.parse_config()
    client = spotify_client.Client(config["spotify"]["client_id"], config["spotify"]["client_secret"])

    track_ids = list(track_ids_to_remove)
    playlist = Playlist(BACKLOG_ID)
    playlist.remove_tracks(track_ids, client.client)

    # Update local DB
    placeholders = "','".join(track_ids)
    sqlite.query_db(
        sqlite.DATABASE,
        [f"DELETE FROM playlists_tracks WHERE playlist_id = '{BACKLOG_ID}' AND track_id IN ('{placeholders}')"],
    )

    print(f"\nDone. Removed {len(track_ids)} tracks from IR-Backlog-Mar-9.")


if __name__ == "__main__":
    main()
