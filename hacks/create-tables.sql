-- DROP TABLE playlists;
CREATE TABLE IF NOT EXISTS playlists(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- DROP TABLE tracks;
CREATE TABLE IF NOT EXISTS tracks(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- DROP TABLE albums;
CREATE TABLE IF NOT EXISTS albums(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  release_date TEXT,
  updated_at TEXT NOT NULL
);;

-- DROP TABLE artists;
CREATE TABLE IF NOT EXISTS artists(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- DROP TABLE playlists_tracks;
CREATE TABLE IF NOT EXISTS playlists_tracks(
  playlist_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  added_at TEXT NOT NULL,
  PRIMARY KEY (playlist_id, track_id),
  FOREIGN KEY (playlist_id) REFERENCES playlists (id),
  FOREIGN KEY (track_id) REFERENCES tracks (id)
);

-- DROP TABLE tracks_artists;
CREATE TABLE IF NOT EXISTS tracks_artists(
  track_id TEXT NOT NULL,
  artist_id TEXT NOT NULL,
  PRIMARY KEY (track_id, artist_id),
  FOREIGN KEY (track_id) REFERENCES tracks (id),
  FOREIGN KEY (artist_id) REFERENCES artists (id)
);

-- DROP TABLE albums_tracks;
CREATE TABLE IF NOT EXISTS albums_tracks(
  album_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  PRIMARY KEY (album_id, track_id),
  FOREIGN KEY (album_id) REFERENCES albums (id),
  FOREIGN KEY (track_id) REFERENCES tracks (id)
);

-- DROP TABLE artists_genres;
CREATE TABLE IF NOT EXISTS artists_genres(
  artist_id TEXT NOT NULL,
  genre TEXT NOT NULL,
  PRIMARY KEY (artist_id, genre),
  FOREIGN KEY (artist_id) REFERENCES artists (id)
);

-- DROP TABLE albums_artists;
CREATE TABLE IF NOT EXISTS albums_artists(
   album_id TEXT NOT NULL,
   artist_id TEXT NOT NULL,
   PRIMARY KEY (album_id, artist_id),
   FOREIGN KEY (album_id) REFERENCES albums (id),
   FOREIGN KEY (artist_id) REFERENCES artists (id)
 )
