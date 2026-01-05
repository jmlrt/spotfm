"""Duplicate track detection functionality.

This module provides functions to find duplicate tracks in the Spotify database
using both exact ID matching and fuzzy name matching.
"""

import csv
import logging
from itertools import combinations
from pathlib import Path

from rapidfuzz import fuzz

from spotfm import utils


def get_playlists_for_track(track_id):
    """Get all playlists containing a specific track.

    Args:
        track_id: Spotify track ID

    Returns:
        List of (playlist_id, playlist_name) tuples
    """
    query = f"""
        SELECT p.id, p.name
        FROM playlists p
        JOIN playlists_tracks pt ON p.id = pt.playlist_id
        WHERE pt.track_id = '{track_id}'
        ORDER BY p.name
    """
    results = utils.select_db(utils.DATABASE, query).fetchall()
    return [(row[0], row[1]) for row in results]


def get_all_tracks_with_playlists(excluded_playlist_ids=None):
    """Get all tracks from the database with their playlists.

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude

    Returns:
        Dict mapping track_id to dict with track info and playlist list
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    # Build exclusion clause
    exclusion_clause = ""
    if excluded_playlist_ids:
        excluded_ids = "','".join(excluded_playlist_ids)
        exclusion_clause = f"AND p.id NOT IN ('{excluded_ids}')"

    query = f"""
        SELECT DISTINCT
            t.id,
            t.name,
            GROUP_CONCAT(a.name, ', ') as artists
        FROM tracks t
        JOIN playlists_tracks pt ON t.id = pt.track_id
        JOIN playlists p ON pt.playlist_id = p.id
        LEFT JOIN tracks_artists ta ON t.id = ta.track_id
        LEFT JOIN artists a ON ta.artist_id = a.id
        WHERE 1=1 {exclusion_clause}
        GROUP BY t.id, t.name
    """
    results = utils.select_db(utils.DATABASE, query).fetchall()

    tracks = {}
    for row in results:
        track_id, track_name, artists = row
        playlists = get_playlists_for_track(track_id)
        tracks[track_id] = {
            "name": track_name,
            "artists": artists or "",
            "playlists": playlists,
            "full_name": f"{artists} - {track_name}" if artists else track_name,
        }

    return tracks


def find_duplicate_ids(excluded_playlist_ids=None, output_file=None):
    """Find tracks that appear multiple times (exact ID match).

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude
        output_file: Path to CSV output file (optional)

    Returns:
        List of dicts with duplicate track information
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    tracks = get_all_tracks_with_playlists(excluded_playlist_ids)
    duplicates = []

    # Group tracks by ID and count playlists
    for _track_id, track_info in tracks.items():
        if len(track_info["playlists"]) > 1:
            playlist_names = [f"{pid}_{pname}" for pid, pname in track_info["playlists"]]
            duplicates.append(
                {
                    "type": "ID",
                    "track": track_info["full_name"],
                    "count": len(track_info["playlists"]),
                    "playlists": ",".join(playlist_names),
                }
            )

    # Sort by count (most duplicates first)
    duplicates.sort(key=lambda x: x["count"], reverse=True)

    # Output results
    if output_file:
        write_duplicates_csv(duplicates, output_file)
    else:
        for dup in duplicates:
            print(f"Dupe ID;{dup['track']};{dup['playlists']}")

    logging.info(f"Found {len(duplicates)} tracks with duplicate IDs")
    return duplicates


def find_duplicate_names(excluded_playlist_ids=None, output_file=None, threshold=95):
    """Find tracks with similar names using fuzzy matching.

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude
        output_file: Path to CSV output file (optional)
        threshold: Minimum similarity score (0-100) to consider a duplicate

    Returns:
        List of dicts with similar track pairs
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    tracks = get_all_tracks_with_playlists(excluded_playlist_ids)
    track_list = [(tid, tinfo) for tid, tinfo in tracks.items()]

    duplicates = []
    total_pairs = len(list(combinations(range(len(track_list)), 2)))

    logging.info(f"Comparing {len(track_list)} tracks ({total_pairs:,} pairs)...")

    # Compare all pairs of tracks
    for i, (track1_id, track1_info) in enumerate(track_list):
        if i % 100 == 0:
            logging.info(f"Processing track {i}/{len(track_list)}...")

        for track2_id, track2_info in track_list[i + 1 :]:
            # Skip if same track ID
            if track1_id == track2_id:
                continue

            name1 = track1_info["full_name"].lower()
            name2 = track2_info["full_name"].lower()

            # Try different fuzzy matching algorithms
            ratio_type = None
            score = 0

            # 1. Exact ratio
            score = fuzz.ratio(name1, name2)
            if score >= threshold:
                ratio_type = "ratio"
            # 2. Partial ratio (substring matching)
            elif (score := fuzz.partial_ratio(name1, name2)) >= threshold:
                ratio_type = "partial_ratio"
            # 3. Token sort ratio (word order independent)
            elif (score := fuzz.token_sort_ratio(name1, name2)) >= threshold:
                ratio_type = "token_sort_ratio"
            # 4. Token set ratio (ignores duplicated words)
            elif (score := fuzz.token_set_ratio(name1, name2)) >= threshold:
                ratio_type = "token_set_ratio"

            if ratio_type:
                playlist1_names = [f"{pid}_{pname}" for pid, pname in track1_info["playlists"]]
                playlist2_names = [f"{pid}_{pname}" for pid, pname in track2_info["playlists"]]

                duplicates.append(
                    {
                        "track1": track1_info["full_name"],
                        "artists1": track1_info["artists"],
                        "playlists1": ",".join(playlist1_names),
                        "track2": track2_info["full_name"],
                        "artists2": track2_info["artists"],
                        "playlists2": ",".join(playlist2_names),
                        "score": score,
                        "ratio_type": ratio_type,
                    }
                )

    # Sort by score (highest first)
    duplicates.sort(key=lambda x: x["score"], reverse=True)

    # Output results
    if output_file:
        write_similarity_csv(duplicates, output_file)
    else:
        for dup in duplicates:
            print(
                f"Dupe Name;{dup['track1']};{dup['track2']};"
                f"{dup['score']};{dup['ratio_type']};{dup['playlists1']};{dup['playlists2']}"
            )

    logging.info(f"Found {len(duplicates)} similar track pairs")
    return duplicates


def write_duplicates_csv(duplicates, output_file):
    """Write duplicate IDs to CSV file.

    Args:
        duplicates: List of duplicate track dicts
        output_file: Path to output CSV file
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as csvfile:
        fieldnames = ["Type", "Track", "Count", "Playlists"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for dup in duplicates:
            writer.writerow(
                {
                    "Type": dup["type"],
                    "Track": dup["track"],
                    "Count": dup["count"],
                    "Playlists": dup["playlists"],
                }
            )

    logging.info(f"Wrote {len(duplicates)} duplicates to {output_path}")


def write_similarity_csv(duplicates, output_file):
    """Write similar track pairs to CSV file.

    Args:
        duplicates: List of similar track pair dicts
        output_file: Path to output CSV file
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as csvfile:
        fieldnames = [
            "Playlists 1",
            "Artist 1",
            "Title 1",
            "Title 2",
            "Artist 2",
            "Playlists 2",
            "Score",
            "Ratio type",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()

        for dup in duplicates:
            writer.writerow(
                {
                    "Playlists 1": dup["playlists1"],
                    "Artist 1": dup["artists1"],
                    "Title 1": dup["track1"],
                    "Title 2": dup["track2"],
                    "Artist 2": dup["artists2"],
                    "Playlists 2": dup["playlists2"],
                    "Score": dup["score"],
                    "Ratio type": dup["ratio_type"],
                }
            )

    logging.info(f"Wrote {len(duplicates)} similar pairs to {output_path}")
