"""Duplicate track detection functionality.

This module provides functions to find duplicate tracks in the Spotify database
using both exact ID matching and fuzzy name matching.
"""

import csv
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz, process

from spotfm import sqlite


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
    results = sqlite.select_db(sqlite.DATABASE, query).fetchall()
    return [(row[0], row[1]) for row in results]


def get_tracks_with_playlists_optimized(excluded_playlist_ids=None):
    """Get all tracks from the database with their playlists - optimized version.

    Uses single JOIN query with GROUP_CONCAT to avoid N+1 query problem.
    Uses parameterized queries to prevent SQL injection.
    Uses query_db_select() for automatic connection cleanup.

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude

    Returns:
        Dict mapping track_id to dict with track info, playlist list, and count
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    # Build parameterized exclusion clause
    exclusion_clause = ""
    params = []
    if excluded_playlist_ids:
        placeholders = ",".join(["?"] * len(excluded_playlist_ids))
        exclusion_clause = f"AND p.id NOT IN ({placeholders})"
        params.extend(excluded_playlist_ids)

    # Single query with GROUP_CONCAT to aggregate playlists in SQL
    query = f"""
        SELECT
            t.id AS track_id,
            t.name AS track_name,
            REPLACE((SELECT GROUP_CONCAT(DISTINCT artist_name)
                     FROM (SELECT a2.name AS artist_name
                           FROM tracks_artists ta2
                           JOIN artists a2 ON ta2.artist_id = a2.id
                           WHERE ta2.track_id = t.id)), ',', ', ') AS artists,
            GROUP_CONCAT(p.id || '~' || p.name, '|||') AS playlists,
            COUNT(DISTINCT p.id) AS playlist_count
        FROM tracks t
        JOIN playlists_tracks pt ON t.id = pt.track_id
        JOIN playlists p ON pt.playlist_id = p.id
        WHERE 1=1 {exclusion_clause}
        GROUP BY t.id, t.name
        HAVING playlist_count >= 1
        ORDER BY playlist_count DESC
    """

    results = sqlite.query_db_select(sqlite.DATABASE, query, tuple(params))

    # Parse concatenated playlists
    tracks = {}
    for row in results:
        track_id, track_name, artists, playlists_concat, playlist_count = row
        playlist_list = []
        if playlists_concat:
            for playlist_str in playlists_concat.split("|||"):
                if "~" in playlist_str:
                    pid, pname = playlist_str.split("~", 1)
                    playlist_list.append((pid, pname))

        tracks[track_id] = {
            "name": track_name,
            "artists": artists or "",
            "playlists": playlist_list,
            "playlist_count": playlist_count,
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

    tracks = get_tracks_with_playlists_optimized(excluded_playlist_ids)
    duplicates = []

    # Filter for tracks in multiple playlists (already sorted by count DESC in SQL)
    for _track_id, track_info in tracks.items():
        if track_info["playlist_count"] > 1:
            playlist_names = [f"{pid}_{pname}" for pid, pname in track_info["playlists"]]
            duplicates.append(
                {
                    "type": "ID",
                    "track": track_info["full_name"],
                    "count": track_info["playlist_count"],
                    "playlists": ",".join(playlist_names),
                }
            )

    # Output results
    if output_file:
        write_duplicates_csv(duplicates, output_file)
    else:
        for dup in duplicates:
            print(f"Dupe ID - {dup['track']} - {dup['playlists']}")

    logging.info(f"Found {len(duplicates)} tracks with duplicate IDs")
    return duplicates


def get_fuzzy_match_candidates(excluded_playlist_ids=None, min_name_length=3):
    """Get tracks grouped for efficient fuzzy matching.

    Returns tracks with prefix and length metadata for grouping to reduce
    the number of comparisons from O(n²) to manageable size.

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude
        min_name_length: Minimum track name length to include

    Returns:
        List of dicts with track info plus name_prefix and name_length
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    # Build parameterized exclusion clause
    exclusion_clause = ""
    params = [min_name_length]
    if excluded_playlist_ids:
        placeholders = ",".join(["?"] * len(excluded_playlist_ids))
        exclusion_clause = f"AND p.id NOT IN ({placeholders})"
        params.extend(excluded_playlist_ids)

    # Query with prefix and length metadata for grouping
    query = f"""
        SELECT
            t.id AS track_id,
            t.name AS track_name,
            REPLACE((SELECT GROUP_CONCAT(DISTINCT artist_name)
                     FROM (SELECT a2.name AS artist_name
                           FROM tracks_artists ta2
                           JOIN artists a2 ON ta2.artist_id = a2.id
                           WHERE ta2.track_id = t.id)), ',', ', ') AS artists,
            GROUP_CONCAT(p.id || '~' || p.name, '|||') AS playlists,
            LOWER(SUBSTR(t.name, 1, 3)) AS name_prefix,
            LENGTH(t.name) AS name_length
        FROM tracks t
        JOIN playlists_tracks pt ON t.id = pt.track_id
        JOIN playlists p ON pt.playlist_id = p.id
        WHERE LENGTH(t.name) >= ? {exclusion_clause}
        GROUP BY t.id, t.name
        ORDER BY name_prefix, name_length
    """

    results = sqlite.query_db_select(sqlite.DATABASE, query, tuple(params))

    # Parse results into list of candidate dicts
    candidates = []
    for row in results:
        track_id, track_name, artists, playlists_concat, name_prefix, name_length = row
        playlist_list = []
        if playlists_concat:
            for playlist_str in playlists_concat.split("|||"):
                if "~" in playlist_str:
                    pid, pname = playlist_str.split("~", 1)
                    playlist_list.append((pid, pname))

        full_name = f"{artists} - {track_name}" if artists else track_name

        candidates.append(
            {
                "id": track_id,
                "name": track_name,
                "artists": artists or "",
                "playlists": playlist_list,
                "full_name": full_name,
                "name_prefix": name_prefix,
                "name_length": name_length,
            }
        )

    return candidates


def is_likely_false_positive(track1_name, track2_name, track1_artists, track2_artists):
    """Filter out common false positive patterns in duplicate detection.

    Args:
        track1_name: First track name (without artist prefix)
        track2_name: Second track name (without artist prefix)
        track1_artists: First track's artists string
        track2_artists: Second track's artists string

    Returns:
        True if this is likely a false positive, False if it's a legitimate duplicate candidate
    """
    import re

    name1_lower = track1_name.lower().strip()
    name2_lower = track2_name.lower().strip()

    # Pattern 0: Very short track names are almost always false positives
    # except for exact matches or very similar remixes
    min_len = min(len(name1_lower), len(name2_lower))
    max_len = max(len(name1_lower), len(name2_lower))

    if min_len <= 5:
        # Allow only if they're extremely similar (same base word + remix marker)
        # e.g., "Ice" vs "Ice Cream" MIGHT be okay if high similarity score
        # but "You" vs "You Got the Stuff" is false positive
        # Check if longer track has significantly more content
        shorter = name1_lower if len(name1_lower) < len(name2_lower) else name2_lower
        longer = name2_lower if len(name1_lower) < len(name2_lower) else name1_lower

        # If names aren't identical and longer has extra words beyond shorter
        if shorter != longer:
            # Check if longer starts with shorter + space (e.g., "Bad" vs "Bad Amapiano")
            if longer.startswith(shorter + " "):
                # This might be okay ONLY if the extra part is a remix/version marker
                extra_part = longer[len(shorter) :].strip()
                remix_markers = ["remix", "edit", "mix", "version", "remaster", "feat", "ft", "("]
                # If extra part doesn't start with a remix marker, it's a different song
                if not any(extra_part.startswith((marker, "- ")) for marker in remix_markers):
                    return True
            # If shorter is just substring (not at start), definitely false positive
            elif shorter in longer:
                return True
            # Completely different short words
            else:
                return True

    # Pattern 1: Track name is just an artist name from the other track
    # e.g., "Latto" vs "Make Em Say (feat. Latto)"
    # Check if one track name appears as an artist in the other track
    all_artists1 = track1_artists.lower().replace(",", " ").split()
    all_artists2 = track2_artists.lower().replace(",", " ").split()

    # If track1 name is very short and appears in track2's artists
    if len(track1_name) <= 15:
        for artist in all_artists2:
            if name1_lower == artist or (len(name1_lower) > 3 and name1_lower in artist):
                # This is likely a false positive - track name is just an artist name
                # Exception: if the track name clearly appears in the other track (same root)
                # BUT not if it only appears in "(feat. ...)" credits
                # Remove feat. credits from name2 to check core track name
                core_name2 = re.sub(r"\(feat\..*?\)", "", name2_lower, flags=re.IGNORECASE).strip()
                # Only allow exception if name1 appears in CORE track name (not just in credits)
                if not (
                    name1_lower in core_name2
                    and (core_name2.startswith((name1_lower + " ", name1_lower + " (")) or name1_lower == core_name2)
                ):
                    return True

    # Same check for track2
    if len(track2_name) <= 15:
        for artist in all_artists1:
            if name2_lower == artist or (len(name2_lower) > 3 and name2_lower in artist):
                # Remove feat. credits from name1 to check core track name
                core_name1 = re.sub(r"\(feat\..*?\)", "", name1_lower, flags=re.IGNORECASE).strip()
                # Only allow exception if name2 appears in CORE track name (not just in credits)
                if not (
                    name2_lower in core_name1
                    and (core_name1.startswith((name2_lower + " ", name2_lower + " (")) or name2_lower == core_name1)
                ):
                    return True

    # Pattern 2: Very short common words that are just substrings
    # e.g., "You" vs "All Because of You", "One" vs "Gone Baby, Don't Be Long"
    min_len = min(len(name1_lower), len(name2_lower))
    max_len = max(len(name1_lower), len(name2_lower))

    # If one is very short (< 8 chars) and length ratio is too different (> 3x)
    if min_len < 8 and max_len / min_len > 3:
        # Check if the short one is just a substring of the longer one
        shorter = name1_lower if len(name1_lower) < len(name2_lower) else name2_lower
        longer = name2_lower if len(name1_lower) < len(name2_lower) else name1_lower

        # If short word appears in longer but not as a main component
        # (i.e., not at start and not the core track name)
        if shorter in longer and not longer.startswith(shorter):
            # It's likely a false positive unless they share very similar core content
            return True

    # Pattern 3: Different track titles with only shared featured artist
    # e.g., "All Bad (feat. Anderson .Paak)" vs "RNP (feat. Anderson .Paak)"
    # Strip featured artist info and compare core track names
    # Remove (feat. ...) and similar patterns
    core1 = re.sub(r"\(feat\..*?\)", "", name1_lower, flags=re.IGNORECASE).strip()
    core2 = re.sub(r"\(feat\..*?\)", "", name2_lower, flags=re.IGNORECASE).strip()

    # If core names are very different (< 60% similarity) and both have feat. credits
    if "feat" in name1_lower and "feat" in name2_lower:
        core_similarity = fuzz.ratio(core1, core2)
        if core_similarity < 60:
            return True

    # Pattern 4: Length ratio check - if too different in length, likely not duplicates
    # unless one is clearly a remix/extended version
    if max_len > 0:
        length_ratio = min_len / max_len
        # If length ratio < 0.25 (one is 4x longer), likely false positive
        # UNLESS the shorter name is contained at the start of longer (e.g., "Bad" vs "Bad - Remix")
        if length_ratio < 0.25:
            shorter = name1_lower if len(name1_lower) < len(name2_lower) else name2_lower
            longer = name2_lower if len(name1_lower) < len(name2_lower) else name1_lower
            # Check if it's a clear remix/version pattern
            if not (longer.startswith(shorter) or shorter.startswith(longer.split()[0])):
                return True

    return False


def find_duplicate_names(excluded_playlist_ids=None, output_file=None, threshold=95):
    """Find tracks with similar names using fuzzy matching - optimized version.

    Uses prefix grouping and RapidFuzz batch API to reduce O(n²) comparisons.
    Includes secondary pass for same-artist tracks to catch cross-prefix duplicates.
    Includes progress logging for long-running operations.

    Args:
        excluded_playlist_ids: List of playlist IDs to exclude
        output_file: Path to CSV output file (optional)
        threshold: Minimum similarity score (0-100) to consider a duplicate

    Returns:
        List of dicts with similar track pairs
    """
    if excluded_playlist_ids is None:
        excluded_playlist_ids = []

    start_time = datetime.now()
    logging.info(f"Starting fuzzy matching at {start_time.strftime('%H:%M:%S')}")

    # Get candidates with prefix metadata
    candidates = get_fuzzy_match_candidates(excluded_playlist_ids)
    logging.info(f"Loaded {len(candidates)} tracks for comparison")

    duplicates = []
    total_comparisons = 0
    seen_pairs = set()  # Track processed pairs to avoid duplicates

    # === PASS 1: Compare tracks within same track name prefix ===
    prefix_groups = defaultdict(list)
    for candidate in candidates:
        prefix_groups[candidate["name_prefix"]].append(candidate)

    logging.info(f"Pass 1: Organized into {len(prefix_groups)} prefix groups")

    # Process each prefix group independently
    for group_idx, (prefix, group) in enumerate(prefix_groups.items(), 1):
        if len(group) < 2:
            continue

        # Log progress for significant groups
        if len(group) >= 10:
            logging.info(f"  [{group_idx}/{len(prefix_groups)}] Prefix '{prefix}': {len(group)} tracks")

        # Pre-lowercase all names once
        full_names = [c["full_name"].lower() for c in group]

        # Compare each track with remaining tracks in group
        for i, track1 in enumerate(group):
            if i >= len(group) - 1:
                continue

            remaining_names = full_names[i + 1 :]
            remaining_tracks = group[i + 1 :]
            name1 = full_names[i]

            # Use RapidFuzz batch API with score_cutoff for fast early rejection
            # Start with token_set_ratio as it's most lenient and catches all valid matches
            matches = process.extract(
                name1,
                remaining_names,
                scorer=fuzz.token_set_ratio,
                score_cutoff=threshold,
                limit=None,
                processor=None,  # Already lowercased
            )

            total_comparisons += len(remaining_names)

            # Process matches
            for match_text, score, match_idx in matches:
                track2 = remaining_tracks[match_idx]

                # Skip if same track ID
                if track1["id"] == track2["id"]:
                    continue

                # Create unique pair key to avoid duplicates
                pair_key = tuple(sorted([track1["id"], track2["id"]]))
                if pair_key in seen_pairs:
                    continue

                # Filter out false positives
                if is_likely_false_positive(track1["name"], track2["name"], track1["artists"], track2["artists"]):
                    continue

                seen_pairs.add(pair_key)

                # Test all algorithms to find which one matched best
                ratio_type = "token_set_ratio"
                best_score = score

                # Try other algorithms to find the best match type
                algorithms = [
                    ("ratio", fuzz.ratio),
                    ("partial_ratio", fuzz.partial_ratio),
                    ("token_sort_ratio", fuzz.token_sort_ratio),
                ]

                for algo_name, algo_func in algorithms:
                    algo_score = algo_func(name1, match_text)
                    if algo_score > best_score:
                        best_score = algo_score
                        ratio_type = algo_name

                playlist1_names = [f"{pid}_{pname}" for pid, pname in track1["playlists"]]
                playlist2_names = [f"{pid}_{pname}" for pid, pname in track2["playlists"]]

                duplicates.append(
                    {
                        "track1": track1["name"],
                        "artists1": track1["artists"],
                        "playlists1": ",".join(playlist1_names),
                        "track2": track2["name"],
                        "artists2": track2["artists"],
                        "playlists2": ",".join(playlist2_names),
                        "score": best_score,
                        "ratio_type": ratio_type,
                    }
                )

    pass1_matches = len(duplicates)
    logging.info(f"Pass 1 completed: {pass1_matches} matches found")

    # === PASS 2: Compare tracks with shared artists (cross-prefix) ===
    logging.info("Pass 2: Checking tracks with shared artists across different prefixes")

    # Build artist index: map each artist to list of tracks
    artist_to_tracks = defaultdict(list)
    for candidate in candidates:
        if candidate["artists"]:  # Only process tracks with artists
            # Split artists and index each one separately
            artists_list = [a.strip().lower() for a in candidate["artists"].split(",")]
            for artist in artists_list:
                if artist:  # Skip empty strings
                    artist_to_tracks[artist].append(candidate)

    # Find tracks that share at least one artist
    logging.info(f"  Indexed {len(artist_to_tracks)} unique artists")

    # Build pairs of tracks that share at least one artist (but aren't already compared in pass1)
    pass2_pairs_to_check = {}  # key: (track1_id, track2_id), value: (track1, track2)

    for _artist, tracks in artist_to_tracks.items():
        if len(tracks) < 2:
            continue

        # Compare all tracks by this artist
        for i, track1 in enumerate(tracks):
            for track2 in tracks[i + 1 :]:
                # Skip if same track ID
                if track1["id"] == track2["id"]:
                    continue

                # Create unique pair key
                pair_key = tuple(sorted([track1["id"], track2["id"]]))

                # Skip if already found in pass 1
                if pair_key in seen_pairs:
                    continue

                # Skip if they have same prefix (already checked in pass 1)
                if track1["name_prefix"] == track2["name_prefix"]:
                    continue

                # Add to pairs to check
                pass2_pairs_to_check[pair_key] = (track1, track2)

    logging.info(f"  Found {len(pass2_pairs_to_check)} cross-prefix pairs to check")

    pass2_comparisons = len(pass2_pairs_to_check)
    # Use lower threshold for pass2 since we already know they share an artist
    pass2_threshold = max(90, threshold - 5)  # At least 90, or 5 points below main threshold

    for pair_key, (track1, track2) in pass2_pairs_to_check.items():
        name1 = track1["name"].lower()
        name2 = track2["name"].lower()

        # Test with partial_ratio first (most lenient for substring matches)
        score = fuzz.partial_ratio(name1, name2)

        if score < pass2_threshold:
            continue

        # Filter out false positives
        if is_likely_false_positive(track1["name"], track2["name"], track1["artists"], track2["artists"]):
            continue

        # Found a match - mark as seen
        seen_pairs.add(pair_key)

        # Test all algorithms on TRACK NAMES to find best match
        ratio_type = "partial_ratio"
        best_score = score

        algorithms = [
            ("ratio", fuzz.ratio),
            ("token_sort_ratio", fuzz.token_sort_ratio),
            ("token_set_ratio", fuzz.token_set_ratio),
        ]

        for algo_name, algo_func in algorithms:
            algo_score = algo_func(name1, name2)
            if algo_score > best_score:
                best_score = algo_score
                ratio_type = algo_name

        playlist1_names = [f"{pid}_{pname}" for pid, pname in track1["playlists"]]
        playlist2_names = [f"{pid}_{pname}" for pid, pname in track2["playlists"]]

        duplicates.append(
            {
                "track1": track1["name"],
                "artists1": track1["artists"],
                "playlists1": ",".join(playlist1_names),
                "track2": track2["name"],
                "artists2": track2["artists"],
                "playlists2": ",".join(playlist2_names),
                "score": best_score,
                "ratio_type": ratio_type,
            }
        )

    pass2_matches = len(duplicates) - pass1_matches
    logging.info(f"Pass 2 completed: {pass2_matches} additional matches found ({pass2_comparisons:,} comparisons)")

    # Sort by score (highest first)
    duplicates.sort(key=lambda x: x["score"], reverse=True)

    # Calculate elapsed time
    total_comparisons += pass2_comparisons
    elapsed = (datetime.now() - start_time).total_seconds()
    logging.info(f"Completed in {elapsed:.1f}s - {total_comparisons:,} comparisons, {len(duplicates)} matches found")

    # Output results
    if output_file:
        write_similarity_csv(duplicates, output_file)
    else:
        for dup in duplicates:
            print(
                f"Dupe Name - {dup['artists1']} - {dup['track1']} - {dup['artists2']} - {dup['track2']} - "
                f"{dup['score']} - {dup['ratio_type']} - {dup['playlists1']} - {dup['playlists2']}"
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
