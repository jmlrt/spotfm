-- Database indexes for spotfm
-- Run with: python hacks/manage_db.py add-indexes

-- Index foreign keys in playlists_tracks (most critical for duplicate detection)
CREATE INDEX IF NOT EXISTS idx_playlists_tracks_playlist_id
  ON playlists_tracks(playlist_id);
CREATE INDEX IF NOT EXISTS idx_playlists_tracks_track_id
  ON playlists_tracks(track_id);

-- Index foreign keys in tracks_artists
CREATE INDEX IF NOT EXISTS idx_tracks_artists_track_id
  ON tracks_artists(track_id);
CREATE INDEX IF NOT EXISTS idx_tracks_artists_artist_id
  ON tracks_artists(artist_id);

-- Index foreign keys in albums_tracks
CREATE INDEX IF NOT EXISTS idx_albums_tracks_album_id
  ON albums_tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_albums_tracks_track_id
  ON albums_tracks(track_id);

-- Index foreign keys in albums_artists
CREATE INDEX IF NOT EXISTS idx_albums_artists_album_id
  ON albums_artists(album_id);
CREATE INDEX IF NOT EXISTS idx_albums_artists_artist_id
  ON albums_artists(artist_id);

-- Index foreign keys in artists_genres
CREATE INDEX IF NOT EXISTS idx_artists_genres_artist_id
  ON artists_genres(artist_id);

-- Composite index for duplicate detection (track_id, playlist_id)
CREATE INDEX IF NOT EXISTS idx_playlists_tracks_composite
  ON playlists_tracks(track_id, playlist_id);
