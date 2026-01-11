from spotfm import utils

REDIRECT_URI = "http://127.0.0.1:9090"
SCOPE = "user-library-read playlist-read-private playlist-read-collaborative"
TOKEN_CACHE_FILE = utils.WORK_DIR / "spotify-token-cache"
BATCH_SIZE = 50  # Spotify API maximum for tracks(), albums(), artists()
MARKET = "FR"
