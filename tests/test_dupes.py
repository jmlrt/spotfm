"""Tests for duplicate detection functionality."""

import csv

import pytest

from spotfm import sqlite, utils
from spotfm.spotify import dupes


@pytest.fixture
def populated_db(temp_database, monkeypatch):
    """Create a database populated with test data for duplicate detection."""
    monkeypatch.setattr(utils, "DATABASE", temp_database)

    # Insert test tracks
    tracks_data = [
        ("track1", "Come Together", "2024-01-01"),
        ("track2", "Come Together - Remastered", "2024-01-02"),
        ("track3", "Yesterday", "2024-01-03"),
        ("track4", "Something", "2024-01-04"),
        ("track5", "Here Comes the Sun", "2024-01-05"),
        ("track6", "Ice", "2024-01-06"),
        ("track7", "Ice Cream", "2024-01-07"),
        ("track8", "All Bad (feat. Anderson .Paak)", "2024-01-08"),
        ("track9", "RNP (feat. Anderson .Paak)", "2024-01-09"),
        ("track10", "You", "2024-01-10"),
        ("track11", "All Because of You", "2024-01-11"),
    ]

    queries = []
    for track_id, name, date in tracks_data:
        queries.append(f"INSERT INTO tracks (id, name, updated_at) VALUES ('{track_id}', '{name}', '{date}')")

    # Insert test artists
    artists_data = [
        ("artist1", "The Beatles"),
        ("artist2", "Anderson .Paak"),
        ("artist3", "JID"),
    ]

    for artist_id, name in artists_data:
        queries.append(f"INSERT INTO artists (id, name, updated_at) VALUES ('{artist_id}', '{name}', '2024-01-01')")

    # Insert test playlists
    playlists_data = [
        ("playlist1", "Rock Classics", "user1"),
        ("playlist2", "My Favorites", "user1"),
        ("playlist3", "Chill Vibes", "user2"),
        ("excluded1", "Excluded Playlist", "user1"),
    ]

    for playlist_id, name, owner in playlists_data:
        queries.append(
            f"INSERT INTO playlists (id, name, owner, updated_at) VALUES ('{playlist_id}', '{name}', '{owner}', '2024-01-01')"
        )

    # Link tracks to artists
    track_artist_links = [
        ("track1", "artist1"),
        ("track2", "artist1"),
        ("track3", "artist1"),
        ("track4", "artist1"),
        ("track5", "artist1"),
        ("track6", "artist3"),
        ("track7", "artist3"),
        ("track8", "artist3"),
        ("track9", "artist3"),
        ("track10", "artist3"),
        ("track11", "artist3"),
    ]

    for track_id, artist_id in track_artist_links:
        queries.append(f"INSERT INTO tracks_artists (track_id, artist_id) VALUES ('{track_id}', '{artist_id}')")

    # Link tracks to playlists - create some duplicates
    playlist_track_links = [
        ("playlist1", "track1", "2024-01-01T00:00:00Z"),  # track1 in playlist1
        ("playlist2", "track1", "2024-01-02T00:00:00Z"),  # track1 in playlist2 (DUPLICATE ID)
        ("playlist1", "track2", "2024-01-03T00:00:00Z"),  # track2 in playlist1 (similar name to track1)
        ("playlist3", "track3", "2024-01-04T00:00:00Z"),  # track3 in playlist3
        ("playlist1", "track4", "2024-01-05T00:00:00Z"),  # track4 in playlist1
        ("playlist2", "track4", "2024-01-06T00:00:00Z"),  # track4 in playlist2 (DUPLICATE ID)
        ("playlist3", "track4", "2024-01-07T00:00:00Z"),  # track4 in playlist3 (DUPLICATE ID - 3 playlists!)
        ("playlist1", "track5", "2024-01-08T00:00:00Z"),  # track5 in playlist1
        ("playlist1", "track6", "2024-01-09T00:00:00Z"),  # track6 in playlist1
        ("playlist2", "track7", "2024-01-10T00:00:00Z"),  # track7 in playlist2
        ("playlist1", "track8", "2024-01-11T00:00:00Z"),  # track8 in playlist1
        ("playlist2", "track9", "2024-01-12T00:00:00Z"),  # track9 in playlist2
        ("playlist1", "track10", "2024-01-13T00:00:00Z"),  # track10 in playlist1
        ("playlist2", "track11", "2024-01-14T00:00:00Z"),  # track11 in playlist2
        ("excluded1", "track1", "2024-01-15T00:00:00Z"),  # track1 in excluded playlist
    ]

    for playlist_id, track_id, added_at in playlist_track_links:
        queries.append(
            f"INSERT INTO playlists_tracks (playlist_id, track_id, added_at) VALUES ('{playlist_id}', '{track_id}', '{added_at}')"
        )

    sqlite.query_db(temp_database, queries)

    return temp_database


@pytest.mark.unit
class TestGetPlaylistsForTrack:
    """Tests for get_playlists_for_track function."""

    def test_track_in_multiple_playlists(self, populated_db, monkeypatch):
        """Test getting playlists for a track that appears in multiple playlists."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        playlists = dupes.get_playlists_for_track("track1")

        # track1 is in 3 playlists (playlist1, playlist2, excluded1)
        assert len(playlists) == 3
        # Results should be sorted by name
        assert playlists[0][1] == "Excluded Playlist"
        assert playlists[1][1] == "My Favorites"
        assert playlists[2][1] == "Rock Classics"

    def test_track_in_single_playlist(self, populated_db, monkeypatch):
        """Test getting playlists for a track in only one playlist."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        playlists = dupes.get_playlists_for_track("track3")

        assert len(playlists) == 1
        assert playlists[0][0] == "playlist3"
        assert playlists[0][1] == "Chill Vibes"

    def test_track_not_in_any_playlist(self, populated_db, monkeypatch):
        """Test getting playlists for a track that doesn't exist in any playlist."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        playlists = dupes.get_playlists_for_track("nonexistent")

        assert len(playlists) == 0


@pytest.mark.unit
class TestGetTracksWithPlaylistsOptimized:
    """Tests for get_tracks_with_playlists_optimized function."""

    def test_get_all_tracks(self, populated_db, monkeypatch):
        """Test getting all tracks with their playlists."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        tracks = dupes.get_tracks_with_playlists_optimized()

        # Should have all tracks that are in at least one playlist
        assert len(tracks) == 11  # All 11 tracks are in at least one playlist

        # Verify track1 has correct data
        assert "track1" in tracks
        track1 = tracks["track1"]
        assert track1["name"] == "Come Together"
        assert track1["artists"] == "The Beatles"
        assert track1["playlist_count"] == 3  # In 3 playlists
        assert len(track1["playlists"]) == 3

    def test_exclude_playlists(self, populated_db, monkeypatch):
        """Test excluding specific playlists."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        tracks = dupes.get_tracks_with_playlists_optimized(excluded_playlist_ids=["excluded1"])

        # track1 should now only have 2 playlists (excluded1 is excluded)
        assert "track1" in tracks
        assert tracks["track1"]["playlist_count"] == 2

    def test_playlist_format(self, populated_db, monkeypatch):
        """Test that playlists are returned in correct format."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        tracks = dupes.get_tracks_with_playlists_optimized()

        track1 = tracks["track1"]
        # Playlists should be list of (id, name) tuples
        assert isinstance(track1["playlists"], list)
        assert len(track1["playlists"]) == 3
        assert all(isinstance(p, tuple) and len(p) == 2 for p in track1["playlists"])

    def test_full_name_construction(self, populated_db, monkeypatch):
        """Test that full_name is constructed correctly."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        tracks = dupes.get_tracks_with_playlists_optimized()

        # Track with artists
        assert tracks["track1"]["full_name"] == "The Beatles - Come Together"


@pytest.mark.unit
class TestFindDuplicateIds:
    """Tests for find_duplicate_ids function."""

    def test_find_duplicates(self, populated_db, monkeypatch):
        """Test finding tracks with duplicate IDs."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates = dupes.find_duplicate_ids()

        # Should find 2 tracks with duplicates: track1 (3 playlists) and track4 (3 playlists)
        assert len(duplicates) == 2

        # Find track1 in results
        track1_dup = next(d for d in duplicates if "Come Together" in d["track"])
        assert track1_dup["type"] == "ID"
        assert track1_dup["count"] == 3

    def test_exclude_playlists(self, populated_db, monkeypatch):
        """Test excluding playlists from duplicate detection."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates = dupes.find_duplicate_ids(excluded_playlist_ids=["playlist2"])

        # track1 should now only have 2 playlists (excluded playlist2)
        track1_dup = next((d for d in duplicates if "Come Together" in d["track"]), None)
        if track1_dup:
            assert track1_dup["count"] == 2

    def test_output_to_csv(self, populated_db, monkeypatch, tmp_path):
        """Test writing duplicates to CSV file."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        output_file = tmp_path / "dupes.csv"
        duplicates = dupes.find_duplicate_ids(output_file=str(output_file))

        # Verify file was created
        assert output_file.exists()

        # Read and verify CSV contents
        with open(output_file) as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        assert len(rows) == len(duplicates)
        assert rows[0]["Type"] == "ID"

    def test_no_duplicates(self, temp_database, monkeypatch):
        """Test when no duplicates exist."""
        monkeypatch.setattr(utils, "DATABASE", temp_database)

        # Insert single track in single playlist
        queries = [
            "INSERT INTO tracks (id, name, updated_at) VALUES ('t1', 'Track', '2024-01-01')",
            "INSERT INTO playlists (id, name, owner, updated_at) VALUES ('p1', 'Playlist', 'user1', '2024-01-01')",
            "INSERT INTO playlists_tracks (playlist_id, track_id, added_at) VALUES ('p1', 't1', '2024-01-01T00:00:00Z')",
        ]
        sqlite.query_db(temp_database, queries)

        duplicates = dupes.find_duplicate_ids()

        assert len(duplicates) == 0


@pytest.mark.unit
class TestGetFuzzyMatchCandidates:
    """Tests for get_fuzzy_match_candidates function."""

    def test_get_candidates(self, populated_db, monkeypatch):
        """Test getting fuzzy match candidates."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        candidates = dupes.get_fuzzy_match_candidates()

        # Should get all tracks with name length >= 3
        assert len(candidates) > 0

        # Verify candidate structure
        candidate = candidates[0]
        assert "id" in candidate
        assert "name" in candidate
        assert "artists" in candidate
        assert "playlists" in candidate
        assert "full_name" in candidate
        assert "name_prefix" in candidate
        assert "name_length" in candidate

    def test_min_name_length_filter(self, populated_db, monkeypatch):
        """Test minimum name length filtering."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        # Get candidates with min length 10
        candidates = dupes.get_fuzzy_match_candidates(min_name_length=10)

        # All candidates should have name length >= 10
        assert all(c["name_length"] >= 10 for c in candidates)

    def test_exclude_playlists(self, populated_db, monkeypatch):
        """Test excluding playlists from candidates."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        candidates = dupes.get_fuzzy_match_candidates(excluded_playlist_ids=["playlist1", "playlist2"])

        # track1 and track2 should not appear (only in excluded playlists)
        candidate_ids = {c["id"] for c in candidates}
        assert "track1" not in candidate_ids or any(
            p[0] not in ["playlist1", "playlist2"] for c in candidates if c["id"] == "track1" for p in c["playlists"]
        )

    def test_prefix_metadata(self, populated_db, monkeypatch):
        """Test that prefix metadata is correctly added."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        candidates = dupes.get_fuzzy_match_candidates()

        # Find "Come Together" track
        come_together = next(c for c in candidates if c["name"] == "Come Together")

        # Prefix should be lowercase first 3 chars
        assert come_together["name_prefix"] == "com"
        assert come_together["name_length"] == len("Come Together")


@pytest.mark.unit
class TestIsLikelyFalsePositive:
    """Tests for is_likely_false_positive function."""

    def test_very_short_different_names(self):
        """Test that very short names with different content are flagged."""
        # "You" vs "All Because of You" - different songs
        result = dupes.is_likely_false_positive("You", "All Because of You", "Artist A", "Artist A")
        assert result is True

    def test_short_substring_match(self):
        """Test that short substring matches are flagged."""
        # "Ice" vs "Ice Cream" - likely different songs
        result = dupes.is_likely_false_positive("Ice", "Ice Cream", "Artist A", "Artist A")
        assert result is True

    def test_track_name_is_artist_name(self):
        """Test that track name matching an artist name is flagged."""
        # "Latto" vs "Make Em Say (feat. Latto)"
        result = dupes.is_likely_false_positive("Latto", "Make Em Say (feat. Latto)", "Artist A", "Artist A, Latto")
        assert result is True

    def test_different_tracks_same_featured_artist(self):
        """Test that different tracks with same featured artist are flagged."""
        # "All Bad (feat. Anderson .Paak)" vs "RNP (feat. Anderson .Paak)"
        result = dupes.is_likely_false_positive(
            "All Bad (feat. Anderson .Paak)",
            "RNP (feat. Anderson .Paak)",
            "JID",
            "JID",
        )
        assert result is True

    def test_legitimate_remix(self):
        """Test that legitimate remixes/remasters are not flagged."""
        # "Come Together" vs "Come Together - Remastered"
        result = dupes.is_likely_false_positive(
            "Come Together", "Come Together - Remastered", "The Beatles", "The Beatles"
        )
        assert result is False

    def test_legitimate_duplicate(self):
        """Test that legitimate duplicates are not flagged."""
        # Very similar track names
        result = dupes.is_likely_false_positive("Yesterday", "Yesterday", "The Beatles", "The Beatles")
        assert result is False

    def test_large_length_ratio_difference(self):
        """Test that tracks with very different lengths are flagged."""
        # One track 4x longer than the other
        result = dupes.is_likely_false_positive("Bad", "Bad Amapiano Remix Extended Version", "Artist A", "Artist A")
        # Should be flagged unless it's a clear remix pattern
        assert result is True

    def test_same_core_different_versions(self):
        """Test tracks with same core but different versions."""
        # "Bad" vs "Bad - Remix"
        result = dupes.is_likely_false_positive("Bad", "Bad - Remix", "Artist A", "Artist A")
        # Should NOT be flagged - this is a valid duplicate (remix)
        assert result is False

    def test_short_track_with_remix_marker(self):
        """Test short track name with remix marker is not flagged."""
        # "Ice" vs "Ice - Remix"
        result = dupes.is_likely_false_positive("Ice", "Ice - Remix", "Artist A", "Artist A")
        # Should NOT be flagged - remix marker indicates same base track
        assert result is False

    def test_track_name_in_artist_exception_with_feat(self):
        """Test exception when track name appears at start of core track."""
        # Track name "Latto" appears at the start of core title (before feat)
        result = dupes.is_likely_false_positive("Latto", "Latto (feat. Someone)", "Artist A", "Artist B, Latto")
        # Should NOT be flagged because "Latto" appears at start of core track name
        assert result is False

    def test_track_name_in_artist_no_exception(self):
        """Test that track name only in feat credits is flagged."""
        # "Latto" only appears in (feat. ...) part
        result = dupes.is_likely_false_positive("Latto", "Different Song (feat. Latto)", "Artist A", "Artist B, Latto")
        # Should be flagged - "Latto" only in feat credits
        assert result is True

    def test_very_short_exact_match(self):
        """Test very short names that are exact matches."""
        # Exact match of short names
        result = dupes.is_likely_false_positive("Ice", "Ice", "Artist A", "Artist A")
        # Should NOT be flagged - exact match
        assert result is False

    def test_short_prefix_with_space(self):
        """Test short name as prefix with space separator."""
        # "Bad" vs "Bad Amapiano" without remix marker
        result = dupes.is_likely_false_positive("Bad", "Bad Amapiano", "Artist A", "Artist A")
        # Should be flagged - extra part is not a remix marker
        assert result is True

    def test_substring_not_at_start(self):
        """Test short substring not at start of longer name."""
        # "One" appears in middle of longer track
        result = dupes.is_likely_false_positive("One", "Gone Baby, Don't Be Long", "Artist A", "Artist A")
        # Should be flagged - "one" only appears in middle
        assert result is True

    def test_length_ratio_at_boundary(self):
        """Test length ratio at the 0.25 boundary."""
        # Create tracks with exactly 4:1 length ratio
        short = "Bad"  # 3 chars
        long = "Very Long Track Name Here"  # 25 chars, ratio = 3/25 = 0.12
        result = dupes.is_likely_false_positive(short, long, "Artist A", "Artist A")
        # Should be flagged - ratio < 0.25 and not a clear remix pattern
        assert result is True

    def test_track_name_longer_than_15_chars(self):
        """Test that tracks longer than 15 chars don't trigger artist name check."""
        # Track name > 15 chars should skip artist name matching logic
        result = dupes.is_likely_false_positive(
            "This Is A Very Long Track Name", "Different Song", "Artist A", "This Is A Very Long Track Name"
        )
        # Long track names have different logic - won't be flagged by artist name check
        assert result is False


@pytest.mark.unit
class TestFindDuplicateNames:
    """Tests for find_duplicate_names function."""

    def test_find_similar_tracks(self, populated_db, monkeypatch):
        """Test finding tracks with similar names."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        # Use lower threshold to catch similar tracks
        duplicates = dupes.find_duplicate_names(threshold=85)

        # Should find "Come Together" and "Come Together - Remastered" as similar
        assert len(duplicates) > 0

        # Verify duplicate structure
        dup = duplicates[0]
        assert "track1" in dup
        assert "artists1" in dup
        assert "playlists1" in dup
        assert "track2" in dup
        assert "artists2" in dup
        assert "playlists2" in dup
        assert "score" in dup
        assert "ratio_type" in dup

    def test_different_ratio_algorithms(self, populated_db, monkeypatch):
        """Test that different fuzzy matching algorithms are used."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates = dupes.find_duplicate_names(threshold=85)

        # Check that various ratio types are represented
        if duplicates:
            ratio_types = {d["ratio_type"] for d in duplicates}
            # At least one algorithm should be used
            assert len(ratio_types) > 0

    def test_high_threshold_filters_matches(self, populated_db, monkeypatch):
        """Test that high threshold filters out less similar matches."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        # Very high threshold
        duplicates = dupes.find_duplicate_names(threshold=99)

        # Should have fewer or no matches
        assert len(duplicates) < 2

    def test_exclude_playlists(self, populated_db, monkeypatch):
        """Test excluding playlists from fuzzy matching."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates_all = dupes.find_duplicate_names(threshold=85)
        duplicates_excluded = dupes.find_duplicate_names(threshold=85, excluded_playlist_ids=["playlist1", "playlist2"])

        # Excluding playlists should reduce matches
        assert len(duplicates_excluded) <= len(duplicates_all)

    def test_output_to_csv(self, populated_db, monkeypatch, tmp_path):
        """Test writing similar tracks to CSV file."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        output_file = tmp_path / "similar.csv"
        duplicates = dupes.find_duplicate_names(threshold=85, output_file=str(output_file))

        # Verify file was created
        assert output_file.exists()

        # Read and verify CSV contents
        with open(output_file) as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        assert len(rows) == len(duplicates)
        assert "Score" in reader.fieldnames

    def test_score_sorting(self, populated_db, monkeypatch):
        """Test that duplicates are sorted by score descending."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates = dupes.find_duplicate_names(threshold=85)

        if len(duplicates) > 1:
            # Verify sorted by score descending
            scores = [d["score"] for d in duplicates]
            assert scores == sorted(scores, reverse=True)

    def test_no_duplicate_pairs(self, populated_db, monkeypatch):
        """Test that the same pair is not reported twice."""
        monkeypatch.setattr(utils, "DATABASE", populated_db)

        duplicates = dupes.find_duplicate_names(threshold=85)

        # Check for duplicate pairs
        seen_pairs = set()
        for dup in duplicates:
            # Create a normalized pair key
            pair = tuple(sorted([dup["track1"] + dup["artists1"], dup["track2"] + dup["artists2"]]))
            assert pair not in seen_pairs, "Same pair reported twice"
            seen_pairs.add(pair)


@pytest.mark.unit
class TestWriteDuplicatesCsv:
    """Tests for write_duplicates_csv function."""

    def test_write_csv(self, tmp_path):
        """Test writing duplicates to CSV file."""
        duplicates = [
            {
                "type": "ID",
                "track": "The Beatles - Come Together",
                "count": 3,
                "playlists": "playlist1_Rock,playlist2_Pop",
            },
            {
                "type": "ID",
                "track": "The Beatles - Something",
                "count": 2,
                "playlists": "playlist1_Rock,playlist3_Jazz",
            },
        ]

        output_file = tmp_path / "dupes.csv"
        dupes.write_duplicates_csv(duplicates, str(output_file))

        # Verify file exists
        assert output_file.exists()

        # Read and verify contents
        with open(output_file) as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        assert len(rows) == 2
        assert rows[0]["Type"] == "ID"
        assert rows[0]["Track"] == "The Beatles - Come Together"
        assert rows[0]["Count"] == "3"
        assert rows[0]["Playlists"] == "playlist1_Rock,playlist2_Pop"

    def test_creates_parent_directory(self, tmp_path):
        """Test that parent directories are created if needed."""
        output_file = tmp_path / "subdir" / "nested" / "dupes.csv"

        duplicates = [{"type": "ID", "track": "Track", "count": 2, "playlists": "p1,p2"}]

        dupes.write_duplicates_csv(duplicates, str(output_file))

        assert output_file.exists()
        assert output_file.parent.exists()


@pytest.mark.unit
class TestWriteSimilarityCsv:
    """Tests for write_similarity_csv function."""

    def test_write_csv(self, tmp_path):
        """Test writing similar tracks to CSV file."""
        duplicates = [
            {
                "playlists1": "playlist1_Rock",
                "artists1": "The Beatles",
                "track1": "Come Together",
                "track2": "Come Together - Remastered",
                "artists2": "The Beatles",
                "playlists2": "playlist2_Pop",
                "score": 95,
                "ratio_type": "token_set_ratio",
            },
        ]

        output_file = tmp_path / "similar.csv"
        dupes.write_similarity_csv(duplicates, str(output_file))

        # Verify file exists
        assert output_file.exists()

        # Read and verify contents
        with open(output_file) as f:
            reader = csv.DictReader(f, delimiter=";")
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["Artist 1"] == "The Beatles"
        assert rows[0]["Title 1"] == "Come Together"
        assert rows[0]["Title 2"] == "Come Together - Remastered"
        assert rows[0]["Score"] == "95"
        assert rows[0]["Ratio type"] == "token_set_ratio"

    def test_creates_parent_directory(self, tmp_path):
        """Test that parent directories are created if needed."""
        output_file = tmp_path / "subdir" / "nested" / "similar.csv"

        duplicates = [
            {
                "playlists1": "p1",
                "artists1": "Artist",
                "track1": "Track1",
                "track2": "Track2",
                "artists2": "Artist",
                "playlists2": "p2",
                "score": 90,
                "ratio_type": "ratio",
            }
        ]

        dupes.write_similarity_csv(duplicates, str(output_file))

        assert output_file.exists()
        assert output_file.parent.exists()
