# SDPB — Spotify Discovery & Queue Bot

A Discord bot that lets everyone in a server search Spotify, share track and playlist links, and build a server-wide listening queue using slash commands.

> **Important playback limitation:** Spotify's Web API does not provide audio streams for a Discord bot to rebroadcast. This project searches and shares Spotify catalog metadata/links; it does not pipe Spotify audio into Discord voice. Members can open links in their own Spotify apps. Do not add stream ripping or unauthorized audio rebroadcasting.

## Features
- `/search query:` Search Spotify tracks and return clickable links.
- `/playlist url:` Inspect a public Spotify playlist and add its tracks to the shared queue.
- `/add url:` Add a Spotify track to the shared queue.
- `/queue` View the server's shared queue.
- `/nowplaying` Show the current queue item.
- `/next` Advance the shared queue.
- `/clearqueue` Clear the server queue (Manage Server permission required).
- Separate queue per Discord server; queue is held in memory and resets when the bot restarts.

## Setup

1. Create a Discord application/bot at https://discord.com/developers/applications. Enable the bot and invite it with `bot` and `applications.commands` scopes. Grant Send Messages and Embed Links.
2. Create an app at https://developer.spotify.com/dashboard and copy its Client ID and Client Secret. Spotify credentials are server-side secrets; never commit them.
3. Install Python 3.11 or newer.
4. Copy `.env.example` to `.env` and fill in the credentials.
5. Install dependencies and run:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Invite the bot to your server, then use `/search` or `/playlist`.

## Configuration
- `DISCORD_TOKEN`: Discord bot token.
- `SPOTIFY_CLIENT_ID`: Spotify app client ID.
- `SPOTIFY_CLIENT_SECRET`: Spotify app client secret.
- `GUILD_ID` (optional): Set a test server ID to sync slash commands quickly. Leave blank to sync globally (global command propagation can take time).

## Shared listening
This bot makes discovery and the queue available to everyone in the server. To hear audio, members open the returned Spotify links in their own Spotify clients. A server-wide Discord voice stream would require an audio source whose license explicitly permits that use; Spotify catalog access alone does not grant that right.
