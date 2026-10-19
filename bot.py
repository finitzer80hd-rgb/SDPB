import os
import re
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotify_account import SpotifyAccountCog

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sdpb")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and configure it.")
if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
    raise RuntimeError("Spotify credentials are missing. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.")

spotify = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def setup_hook():
    await bot.add_cog(SpotifyAccountCog(bot))

@dataclass
class Track:
    name: str
    artists: str
    url: str
    requester: str

    @property
    def label(self) -> str:
        return f"{self.name} — {self.artists}"

# In-memory, server-specific shared queues. Restarting the bot clears them.
queues: dict[int, list[Track]] = defaultdict(list)


def spotify_id(url: str, expected_type: Optional[str] = None) -> Optional[str]:
    match = re.search(r"(?:open\.spotify\.com/)(track|playlist)/([A-Za-z0-9]+)", url)
    if not match:
        return None
    kind, item_id = match.groups()
    if expected_type and kind != expected_type:
        return None
    return f"{kind}:{item_id}"


def track_from_item(item: dict, requester: str) -> Track:
    artists = ", ".join(a["name"] for a in item.get("artists", [])) or "Unknown artist"
    return Track(
        name=item.get("name", "Unknown track"),
        artists=artists,
        url=item.get("external_urls", {}).get("spotify", ""),
        requester=requester,
    )


def add_track(guild_id: int, track: Track) -> int:
    queues[guild_id].append(track)
    return len(queues[guild_id])


async def send_track_list(interaction: discord.Interaction, tracks: list[Track], title: str):
    embed = discord.Embed(title=title, color=discord.Color.green())
    for index, track in enumerate(tracks[:10], start=1):
        embed.add_field(
            name=f"{index}. {track.label}",
            value=f"[Open in Spotify]({track.url}) · added by {discord.utils.escape_markdown(track.requester)}",
            inline=False,
        )
    if len(tracks) > 10:
        embed.set_footer(text=f"Showing 10 of {len(tracks)} results.")
    await interaction.response.send_message(embed=embed)


@bot.event
async def on_ready():
    try:
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info("Synced %s commands to test guild %s", len(synced), GUILD_ID)
        else:
            synced = await bot.tree.sync()
            log.info("Synced %s global commands", len(synced))
    except Exception:
        log.exception("Failed to sync application commands")
    log.info("Logged in as %s (%s)", bot.user, bot.user.id if bot.user else "unknown")


@bot.tree.command(name="search", description="Search Spotify and share tracks with this server")
@app_commands.describe(query="Song title, artist, or both")
async def search(interaction: discord.Interaction, query: str):
    await interaction.response.defer(thinking=True)
    try:
        result = spotify.search(q=query, type="track", limit=8)
        items = result.get("tracks", {}).get("items", [])
        tracks = [track_from_item(item, interaction.user.display_name) for item in items]
        if not tracks:
            await interaction.followup.send("No Spotify tracks found. Try a different search.")
            return
        embed = discord.Embed(title=f'Spotify search: "{query[:200]}"', color=discord.Color.green())
        for i, track in enumerate(tracks, start=1):
            embed.add_field(name=f"{i}. {track.label}", value=f"[Open in Spotify]({track.url})", inline=False)
        embed.set_footer(text="Use /add with a Spotify track URL to add it to the shared server queue.")
        await interaction.followup.send(embed=embed)
    except Exception:
        log.exception("Spotify search failed")
        await interaction.followup.send("Spotify search failed. Check the Spotify API credentials and try again.")


@bot.tree.command(name="add", description="Add a Spotify track to the shared server queue")
@app_commands.describe(url="Spotify track URL")
async def add(interaction: discord.Interaction, url: str):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return
    parsed = spotify_id(url, "track")
    if not parsed:
        await interaction.response.send_message("Please provide a Spotify track URL like https://open.spotify.com/track/…", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        item = spotify.track(parsed.split(":", 1)[1])
        track = track_from_item(item, interaction.user.display_name)
        position = add_track(interaction.guild_id, track)
        await interaction.followup.send(
            f"Added **{discord.utils.escape_markdown(track.label)}** to the shared queue at position **{position}**.\n{track.url}"
        )
    except Exception:
        log.exception("Adding Spotify track failed")
        await interaction.followup.send("Couldn't load that track. Make sure the link is public and valid.")


@bot.tree.command(name="playlist", description="Add tracks from a public Spotify playlist to the shared queue")
@app_commands.describe(url="Spotify playlist URL")
async def playlist(interaction: discord.Interaction, url: str):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return
    parsed = spotify_id(url, "playlist")
    if not parsed:
        await interaction.response.send_message("Please provide a Spotify playlist URL like https://open.spotify.com/playlist/…", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    try:
        playlist_id = parsed.split(":", 1)[1]
        details = spotify.playlist(playlist_id, fields="name,external_urls.spotify")
        added = []
        offset = 0
        while offset < 100:
            page = spotify.playlist_items(
                playlist_id, limit=min(100, 100 - offset), offset=offset,
                fields="items(track(name,artists(name),external_urls.spotify,type)),next"
            )
            items = page.get("items", [])
            if not items:
                break
            for entry in items:
                item = entry.get("track")
                if item and item.get("type") == "track" and item.get("external_urls", {}).get("spotify"):
                    added.append(track_from_item(item, interaction.user.display_name))
            offset += len(items)
            if not page.get("next"):
                break
        # Cap one request to 100 tracks to keep commands responsive and queues manageable.
        added = added[:100]
        queue = queues[interaction.guild_id]
        queue.extend(added)
        playlist_url = details.get("external_urls", {}).get("spotify", url)
        embed = discord.Embed(
            title="Playlist added to shared queue",
            description=f"**{discord.utils.escape_markdown(details.get('name', 'Spotify playlist'))}**\nAdded {len(added)} tracks. Queue now contains {len(queue)} tracks.\n[Open playlist in Spotify]({playlist_url})",
            color=discord.Color.green(),
        )
        if len(added) == 0:
            embed.description = "No playable track entries were found. The playlist may be private or empty."
        await interaction.followup.send(embed=embed)
    except Exception:
        log.exception("Playlist import failed")
        await interaction.followup.send("Couldn't read that playlist. Make sure it is public and the Spotify API credentials are valid.")


@bot.tree.command(name="queue", description="Show the shared queue for this server")
async def queue_command(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return
    current = queues[interaction.guild_id]
    if not current:
        await interaction.response.send_message("The shared queue is empty. Use /search, then /add, or use /playlist.")
        return
    embed = discord.Embed(title=f"Shared queue · {len(current)} tracks", color=discord.Color.blurple())
    for i, track in enumerate(current[:15], start=1):
        embed.add_field(
            name=f"{i}. {track.label}",
            value=f"[Spotify link]({track.url}) · added by {discord.utils.escape_markdown(track.requester)}",
            inline=False,
        )
    if len(current) > 15:
        embed.set_footer(text=f"Showing first 15 of {len(current)} tracks.")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="nowplaying", description="Show the first track in the shared queue")
async def nowplaying(interaction: discord.Interaction):
    if not interaction.guild_id or not queues[interaction.guild_id]:
        await interaction.response.send_message("The shared queue is empty.")
        return
    track = queues[interaction.guild_id][0]
    embed = discord.Embed(title="Up next in the shared queue", description=f"**{track.label}**\n[Open in Spotify]({track.url})", color=discord.Color.green())
    embed.set_footer(text=f"Added by {track.requester} · this bot shares links, not audio streams")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="next", description="Move to the next track in the shared queue")
async def next_track(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return
    current = queues[interaction.guild_id]
    if not current:
        await interaction.response.send_message("The shared queue is empty.")
        return
    finished = current.pop(0)
    if current:
        upcoming = current[0]
        await interaction.response.send_message(
            f"Removed **{discord.utils.escape_markdown(finished.label)}** from the front of the queue. Up next: **{discord.utils.escape_markdown(upcoming.label)}** — {upcoming.url}"
        )
    else:
        await interaction.response.send_message(f"Removed **{discord.utils.escape_markdown(finished.label)}**. The queue is now empty.")


@bot.tree.command(name="clearqueue", description="Clear this server's shared queue (Manage Server required)")
@app_commands.checks.has_permissions(manage_guild=True)
async def clearqueue(interaction: discord.Interaction):
    if not interaction.guild_id:
        await interaction.response.send_message("Use this command inside a server.", ephemeral=True)
        return
    count = len(queues[interaction.guild_id])
    queues[interaction.guild_id].clear()
    await interaction.response.send_message(f"Cleared {count} queued track(s).")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You need the **Manage Server** permission to do that."
    else:
        log.error("Application command error: %s", error, exc_info=error)
        message = "Something went wrong while running that command."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


bot.run(DISCORD_TOKEN)
