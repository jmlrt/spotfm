CREATE TABLE IF NOT EXISTS playlists(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner TEXT NOT NULL,
  date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tracks(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS albums(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  release_date TEXT,
  date TEXT NOT NULL
);;

CREATE TABLE IF NOT EXISTS artists(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS playlists_tracks(
  playlist_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  date TEXT NOT NULL,
  PRIMARY KEY (playlist_id, track_id),
  FOREIGN KEY (playlist_id) REFERENCES playlists (id),
  FOREIGN KEY (track_id) REFERENCES tracks (id)
);

CREATE TABLE IF NOT EXISTS tracks_artists(
  track_id TEXT NOT NULL,
  artist_id TEXT NOT NULL,
  PRIMARY KEY (track_id, artist_id),
  FOREIGN KEY (track_id) REFERENCES tracks (id),
  FOREIGN KEY (artist_id) REFERENCES artists (id)
);

CREATE TABLE IF NOT EXISTS albums_tracks(
  album_id TEXT NOT NULL,
  track_id TEXT NOT NULL,
  PRIMARY KEY (album_id, track_id),
  FOREIGN KEY (album_id) REFERENCES albums (id),
  FOREIGN KEY (track_id) REFERENCES tracks (id)
);

CREATE TABLE IF NOT EXISTS artists_genres(
  artist_id TEXT NOT NULL,
  genre TEXT NOT NULL,
  PRIMARY KEY (artist_id, genre),
  FOREIGN KEY (artist_id) REFERENCES artists (id)
);

CREATE TABLE IF NOT EXISTS albums_artists(
   album_id TEXT NOT NULL,
   artist_id TEXT NOT NULL,
   PRIMARY KEY (album_id, artist_id),
   FOREIGN KEY (album_id) REFERENCES albums (id),
   FOREIGN KEY (artist_id) REFERENCES artists (id)
 )
