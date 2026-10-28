# FAQ

Answers to common questions about running spotfm, with a focus on the Docker
webapp and Spotify authentication.

## Spotify authentication

### The webapp job is stuck at "User authentication requires interaction with your web browser"

This is Spotify OAuth's interactive first-time flow. It only happens when there
is no cached token at `~/.spotfm/spotify-token-cache`. `SpotifyOAuth` opens a
browser and waits for you to paste back the redirect URL — but the paste prompt
is an `input()` call inside the server process. When the server runs in a
container (or detached), you can never reach that prompt, so the job hangs.

The fix: authenticate once so the token cache is written, then re-run the job.

### How do I authenticate when running in Docker?

`docker-compose.yml` mounts the host's `~/.spotfm` into the container
(`~/.spotfm:/root/.spotfm`), and the token cache lives at
`~/.spotfm/spotify-token-cache` (see `spotfm/spotify/constants.py`). So you can
authenticate once on the host and the container picks it up automatically:

1. Open the `https://accounts.spotify.com/authorize?...` URL from the job log
   in your browser, log in, and approve.
2. You'll be redirected to `http://127.0.0.1:9090/?code=...`. The page shows
   "This site can't be reached" — that's expected. Copy the full URL from the
   address bar.
3. Run the CLI on the host and paste that URL when prompted:

   ```bash
   uv run spfm spotify update-playlists
   ```

   You can Ctrl-C once the prompt accepts (or let the sync run to completion).

4. Cancel/clear the stuck webapp job (see below) and re-run it from the web UI.
   It now loads the cached token and runs without any prompt.

Alternative: run the interactive auth inside the container instead, with the
paste prompt attached to a `docker exec` session:

```bash
docker compose exec spotfm-web spfm spotify update-playlists
```

Open the auth URL on your host browser, then paste the redirect URL into the
exec session. Either path writes the same shared token cache.

### How often do I need to re-authenticate?

Only when Spotify's refresh token expires. At that point, repeat the same
one-time host-side auth (`uv run spfm spotify update-playlists`) to refresh the
cache.

## Webapp

### Why did `uv run spotfm ...` fail with "Failed to spawn: spotfm"?

The console entry point is `spfm`, not `spotfm` (see `pyproject.toml`):

```bash
uv run spfm spotify update-playlists
```

### How do I cancel a stuck job in the web UI?

There is currently no cancel button or endpoint — jobs are tracked in an
in-memory dict in `spotfm/web/jobs.py` and are lost on restart. The practical
way to clear a stuck job is to restart the container:

```bash
docker compose restart spotfm-web
```

Then re-trigger the job from the web UI.

Note: a job stuck on the Spotify auth prompt is blocked on an unreachable
`input()` call, so restarting is the only way to clear it short of adding a
cancel feature. Both a cancel feature and an in-webapp first-time auth flow are
tracked in [TODO.md](TODO.md).
