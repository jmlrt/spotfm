#!/usr/bin/env python3
"""Sort a Spotify playlist into decade playlists based on album release date.

Queries the local SQLite DB for all tracks in the source playlist, classifies
each by album release date, then moves them to the appropriate decade playlist
via the Spotify API.

Decade destinations (edit DECADE_PLAYLISTS below to reconfigure):
  pre-1990  → 2HIBRiqksgQj45YXRPbYub
  1990s     → 4svldxXjOSM2B5Bu5hlgjq
  2000s     → 5GfthFCDQX6WGtlfRQy1HJ
  2010s     → 6JOT1me3bHoYIBnhyojEjY
  2020-2023 → 4V8O33t0hSCnK4ABozG6xc
  2024+     → 5gcHhadfjHQ30mI1Sstloo

Run from repo root:
  source .venv/bin/activate && python3 hacks/sort_backlog_by_decade.py --source <playlist_id> [--dry-run]

To rollback a previous run:
  source .venv/bin/activate && python3 hacks/sort_backlog_by_decade.py --rollback sort_manifest_<timestamp>.json
"""

import argparse
import json
import logging
import sys
from datetime import date, datetime

# Destination decade playlists — edit to reconfigure
DECADE_PLAYLISTS = [
    (None, date(1990, 1, 1), "2HIBRiqksgQj45YXRPbYub", "pre-1990"),
    (date(1990, 1, 1), date(2000, 1, 1), "4svldxXjOSM2B5Bu5hlgjq", "1990s"),
    (date(2000, 1, 1), date(2010, 1, 1), "5GfthFCDQX6WGtlfRQy1HJ", "2000s"),
    (date(2010, 1, 1), date(2020, 1, 1), "6JOT1me3bHoYIBnhyojEjY", "2010s"),
    (date(2020, 1, 1), date(2024, 1, 1), "4V8O33t0hSCnK4ABozG6xc", "2020-2023"),
    (date(2024, 1, 1), None, "5gcHhadfjHQ30mI1Sstloo", "2024+"),
]

BATCH_SIZE = 50


def parse_release_date(raw):
    """Parse a Spotify release_date string (YYYY, YYYY-MM, or YYYY-MM-DD) to a date object."""
    if not raw:
        return None
    parts = raw.split("-")
    try:
        if len(parts) == 1:
            return date(int(parts[0]), 1, 1)
        elif len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        else:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError, TypeError:
        return None


def classify_track(release_date):
    """Return (playlist_id, label) for the given release date, or (None, None) if unknown."""
    if release_date is None:
        return None, None
    for start, end, pl_id, label in DECADE_PLAYLISTS:
        if (start is None or release_date >= start) and (end is None or release_date < end):
            return pl_id, label
    return None, None


def batched(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def get_spotify_client(config):
    from spotfm.spotify import client as spotify_client

    return spotify_client.Client(
        config["spotify"]["client_id"],
        config["spotify"]["client_secret"],
        scope="playlist-modify-public playlist-modify-private",
    ).client


def do_rollback(manifest_path):
    """Reverse a previous run: add tracks back to source, remove from destinations, fix DB."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    source_id = manifest["source_id"]
    tracks = manifest["tracks"]

    if not tracks:
        print("Manifest is empty — nothing to roll back.")
        return

    # Group by destination to remove from each
    dest_to_ids = {}
    for t in tracks:
        dest_to_ids.setdefault(t["dest_pl_id"], []).append(t["id"])

    print("\nRollback plan:")
    print(f"  Add {len(tracks)} tracks back to source ({source_id})")
    for pl_id, ids in dest_to_ids.items():
        label = next((lbl for _, _, pid, lbl in DECADE_PLAYLISTS if pid == pl_id), pl_id)
        print(f"  Remove {len(ids)} tracks from {label} ({pl_id})")

    confirm = input("\nProceed with rollback? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    from spotfm import sqlite, utils

    config = utils.parse_config()
    sp = get_spotify_client(config)

    all_ids = [t["id"] for t in tracks]

    # Add back to source first (safer: tracks exist in both during operation)
    print(f"\nAdding {len(all_ids)} tracks back to {source_id}...")
    for batch in batched(all_ids, BATCH_SIZE):
        sp.playlist_add_items(source_id, batch)

    # Remove from each destination
    for pl_id, ids in dest_to_ids.items():
        label = next((lbl for _, _, pid, lbl in DECADE_PLAYLISTS if pid == pl_id), pl_id)
        print(f"Removing {len(ids)} tracks from {label} ({pl_id})...")
        for batch in batched(ids, BATCH_SIZE):
            sp.playlist_remove_all_occurrences_of_items(pl_id, batch)

    # Re-insert into source playlists_tracks — INSERT OR IGNORE makes this idempotent
    added_at_by_id = {t["id"]: t.get("added_at", str(date.today())) for t in tracks}
    for track_id in all_ids:
        added_at = added_at_by_id[track_id]
        sqlite.query_db(
            sqlite.DATABASE,
            [
                f"INSERT OR IGNORE INTO playlists_tracks (playlist_id, track_id, added_at) VALUES ('{source_id}', '{track_id}', '{added_at}')"
            ],
        )

    print(f"\nRollback complete. {len(all_ids)} tracks restored to {source_id}.")
    print("Run `spfm spotify update-playlists` to re-sync the DB with Spotify state.")


def main():
    parser = argparse.ArgumentParser(description="Sort a playlist into decade playlists by album release date")
    parser.add_argument("--source", metavar="PLAYLIST_ID", help="Source playlist ID to sort")
    parser.add_argument("--dry-run", action="store_true", help="Print summary and exit without calling API")
    parser.add_argument("--rollback", metavar="MANIFEST", help="Reverse a previous run using saved manifest file")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.rollback:
        do_rollback(args.rollback)
        return

    if not args.source:
        parser.error("--source PLAYLIST_ID is required")

    source_id = args.source

    from spotfm import sqlite, utils

    # Query all tracks in source playlist with album release dates and added_at
    rows = sqlite.query_db_select(
        sqlite.DATABASE,
        """
        SELECT t.id, t.name, al.release_date, pt.added_at
        FROM tracks t
        JOIN playlists_tracks pt ON t.id = pt.track_id
        LEFT JOIN albums_tracks at_map ON t.id = at_map.track_id
        LEFT JOIN albums al ON at_map.album_id = al.id
        WHERE pt.playlist_id = ?
        """,
        (source_id,),
    )

    if not rows:
        print(f"No tracks found in playlist {source_id}. Nothing to do.")
        return

    # Classify tracks
    decade_buckets = {}  # label -> list of (track_id, track_name, pl_id)
    no_album = []  # (track_id, track_name) with no release date

    for track_id, track_name, release_date_raw, _added_at in rows:
        parsed = parse_release_date(release_date_raw)
        pl_id, label = classify_track(parsed)
        if pl_id is None:
            no_album.append((track_id, track_name))
        else:
            decade_buckets.setdefault(label, []).append((track_id, track_name, pl_id))

    # Print summary
    print(f"\nSource playlist: {source_id}")
    print(f"Total tracks: {len(rows)}")
    print("\nTracks per decade:")
    for _, _, pl_id, label in DECADE_PLAYLISTS:
        count = len(decade_buckets.get(label, []))
        print(f"  {label:12s}  {count:4d} tracks  →  {pl_id}")

    if no_album:
        print(f"\n{len(no_album)} tracks with no album/release-date (will NOT be moved):")
        for track_id, track_name in no_album[:20]:
            print(f"  {track_id}  {track_name}")
        if len(no_album) > 20:
            print(f"  ... and {len(no_album) - 20} more")

    total_to_move = sum(len(v) for v in decade_buckets.values())
    if total_to_move == 0:
        print("\nNo tracks to move.")
        return

    if args.dry_run:
        print(f"\n[dry-run] Would move {total_to_move} tracks. Not calling API.")
        return

    confirm = input(f"\nMove {total_to_move} tracks from {source_id} to decade playlists? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    # Build manifest BEFORE any API calls — enables rollback if script crashes mid-flight
    release_date_by_id = {r[0]: r[2] for r in rows}
    added_at_by_id = {r[0]: r[3] for r in rows}
    manifest_entries = [
        {
            "id": track_id,
            "name": track_name,
            "release_date": release_date_by_id[track_id],
            "added_at": added_at_by_id[track_id],
            "dest_pl_id": pl_id,
            "dest_label": label,
        }
        for label, entries in decade_buckets.items()
        for track_id, track_name, pl_id in entries
    ]
    manifest = {
        "timestamp": datetime.now().isoformat(),
        "source_id": source_id,
        "tracks": manifest_entries,
    }
    manifest_path = f"sort_manifest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"\nManifest saved to {manifest_path} (use --rollback {manifest_path} to undo)")

    config = utils.parse_config()
    sp = get_spotify_client(config)

    # Group by destination playlist for efficient batching
    dest_to_tracks = {}
    for _label, entries in decade_buckets.items():
        for track_id, _track_name, pl_id in entries:
            dest_to_tracks.setdefault(pl_id, []).append(track_id)

    all_moved_ids = []

    # Add to destinations first (safer: tracks exist in both playlists during the operation)
    for pl_id, track_ids in dest_to_tracks.items():
        label = next(lbl for _, _, pid, lbl in DECADE_PLAYLISTS if pid == pl_id)
        print(f"\nAdding {len(track_ids)} tracks to {label} ({pl_id})...")
        for batch in batched(track_ids, BATCH_SIZE):
            sp.playlist_add_items(pl_id, batch)
        all_moved_ids.extend(track_ids)

    # Then remove from source
    print(f"\nRemoving {len(all_moved_ids)} tracks from {source_id}...")
    for batch in batched(all_moved_ids, BATCH_SIZE):
        sp.playlist_remove_all_occurrences_of_items(source_id, batch)

    # Update local DB — remove from source playlist only
    placeholders = "','".join(all_moved_ids)
    sqlite.query_db(
        sqlite.DATABASE,
        [f"DELETE FROM playlists_tracks WHERE playlist_id = '{source_id}' AND track_id IN ('{placeholders}')"],
    )

    print(f"\nDone. Moved {len(all_moved_ids)} tracks into decade playlists.")
    if no_album:
        print(f"{len(no_album)} tracks with no release date remain in {source_id}.")
    print(f"\nTo undo: python3 hacks/sort_backlog_by_decade.py --rollback {manifest_path}")


if __name__ == "__main__":
    main()
