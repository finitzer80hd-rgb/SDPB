# SDPB — Spotify Discovery & Queue Bot

A Discord bot for searching Spotify, sharing playlist links, managing a server-wide discovery queue, and (for one configured owner) controlling playback on their own Spotify Connect devices.

## Features

### Shared server discovery queue
- `/search query:` Search Spotify tracks and return clickable links.
- `/playlist url:` Import up to 100 tracks from a public Spotify playlist into the shared queue.
- `/add url:` Add a Spotify track to the shared queue.
- `/queue`, `/nowplaying`, `/next`, and `/clearqueue` manage the in-memory server queue.
- The shared queue resets when the bot restarts.

### Personal Spotify Premium controls
- `/spotifylogin`: securely authorize the configured Spotify account using Spotify OAuth; never enter your Spotify password in Discord or in `.env`.
- `/myplaylists`: list playlists available to the linked account.
- `/spotifydevices`: list Spotify Connect devices and their IDs.
- `/playplaylist url:`: request playback of a playlist on an active Spotify device. An optional `device_id` can target a device shown by `/spotifydevices`.
- `/spotifypause` and `/spotifyskip`: control playback.

**Important:** This controls audio through your own Spotify app/device. It does not send Spotify audio into Discord voice or make other server members hear the same stream. Spotify's Player API requires Premium for playback control, an available Spotify Connect device, and the approved OAuth permissions. Spotify does not permit rebroadcasting its content through this bot.

Spotify account commands are restricted to the Discord user ID configured in `SPOTIFY_OWNER_DISCORD_ID`, because they control that person's account.

## Ubuntu setup

1. Install Python 3.11 or newer, Git, and virtual-environment support.
2. In the Spotify Developer Dashboard, create/open your Web API app. Add this exact Redirect URI under the app settings:
   `http://127.0.0.1:8888/callback`
3. Copy `.env.example` to `.env` and set the Discord token, Spotify Client ID/Secret, Discord server ID (optional), and your numeric Discord user ID in `SPOTIFY_OWNER_DISCORD_ID`.
4. Install and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
chmod 600 .env
python bot.py
```

If you already cloned the repository, pull the update first:

```bash
cd ~/SDPB
git pull
source .venv/bin/activate
pip install -r requirements.txt
nano .env
```

### First-time linking

1. Make sure the browser you use is running on the same Ubuntu machine as the bot when using the default localhost callback.
2. In Discord, run `/spotifylogin` and open the private authorization link.
3. Approve the requested scopes. The browser should show “Spotify connected successfully”.
4. Open Spotify on a computer, phone, or speaker and ensure a Spotify Connect device is available.
5. Run `/spotifydevices`, then `/myplaylists`, then `/playplaylist` with a playlist URL.
6. Use `/spotifypause` and `/spotifyskip` to control playback.

## Configuration

- `DISCORD_TOKEN`: Discord bot token.
- `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`: Spotify app credentials.
- `GUILD_ID` (optional): Discord server ID for faster slash-command sync.
- `SPOTIFY_REDIRECT_URI`: OAuth callback URL; must exactly match the Spotify Dashboard.
- `SPOTIFY_OWNER_DISCORD_ID`: your numeric Discord user ID. Personal Spotify commands fail closed unless this is set.
- `SPOTIFY_CALLBACK_HOST` / `SPOTIFY_CALLBACK_PORT`: callback listener address and port; defaults to localhost:8888.
- `SPOTIFY_TOKEN_CACHE`: local token cache path. Keep it private; it contains credentials.

## Security and hosting notes

- Never commit `.env` or `.spotify_token_cache`; both are ignored by Git.
- The default OAuth callback uses localhost and works when the browser is on the same Ubuntu machine. If the bot runs on a remote/headless server and the browser is on another computer, configure a reachable HTTPS callback/reverse proxy and set `SPOTIFY_REDIRECT_URI` accordingly; the callback listener must be reachable at that URL.
- Spotify Web API endpoints and Development Mode access may change. If a playlist or playback command returns an API permission error, check the current Spotify Developer Dashboard settings and Spotify Web API documentation.
