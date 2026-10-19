import asyncio
import html
import logging
import os
import re
import secrets
from urllib.parse import urlparse

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands
import spotipy
from spotipy.oauth2 import SpotifyOAuth

log = logging.getLogger("sdpb.spotify_account")

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback").strip()
OWNER_ID = os.getenv("SPOTIFY_OWNER_DISCORD_ID", "").strip()
TOKEN_CACHE = os.getenv("SPOTIFY_TOKEN_CACHE", ".spotify_token_cache")
SCOPES = " ".join([
    "user-read-private",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
])


class SpotifyAccountCog(commands.Cog):
    """Owner-only Spotify Connect controls for one linked Spotify account."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pending_state: str | None = None
        self.web_runner: web.AppRunner | None = None
        self.web_site: web.TCPSite | None = None
        self.callback_lock = asyncio.Lock()

    def oauth(self) -> SpotifyOAuth:
        return SpotifyOAuth(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPES,
            cache_path=TOKEN_CACHE,
            open_browser=False,
            show_dialog=True,
        )

    def spotify(self) -> spotipy.Spotify:
        return spotipy.Spotify(auth_manager=self.oauth(), requests_timeout=15, retries=2)

    def is_owner(self, interaction: discord.Interaction) -> bool:
        return bool(OWNER_ID.isdigit() and interaction.user.id == int(OWNER_ID))

    async def owner_only(self, interaction: discord.Interaction) -> bool:
        if not self.is_owner(interaction):
            raise app_commands.CheckFailure(
                "These commands control the linked Spotify account and are restricted to its configured Discord owner."
            )
        return True

    async def cog_load(self):
        parsed = urlparse(REDIRECT_URI)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            log.warning(
                "SPOTIFY_REDIRECT_URI is not a localhost HTTP URL. Configure a reachable HTTPS callback and reverse proxy if hosting remotely."
            )
        app = web.Application()
        app.router.add_get("/callback", self.handle_callback)
        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        host = os.getenv("SPOTIFY_CALLBACK_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = int(os.getenv("SPOTIFY_CALLBACK_PORT", str(parsed.port or 8888)))
        self.web_site = web.TCPSite(self.web_runner, host=host, port=port)
        try:
            await self.web_site.start()
            log.info("Spotify OAuth callback listening on %s:%s", host, port)
        except OSError:
            log.exception("Could not start Spotify OAuth callback listener on %s:%s", host, port)
            log.error("Stop any other process using this port or change SPOTIFY_CALLBACK_PORT and the matching Spotify redirect URI.")

    async def cog_unload(self):
        if self.web_runner:
            await self.web_runner.cleanup()

    async def handle_callback(self, request: web.Request) -> web.Response:
        error = request.query.get("error")
        if error:
            return web.Response(
                text=f"<h2>Spotify authorization cancelled or denied</h2><p>{html.escape(error)}</p>You can close this tab.",
                content_type="text/html",
                status=400,
            )
        code = request.query.get("code")
        state = request.query.get("state")
        async with self.callback_lock:
            if not self.pending_state or not state or not secrets.compare_digest(state, self.pending_state):
                return web.Response(
                    text="<h2>Invalid or expired login state</h2><p>Run /spotifylogin in Discord and try again.</p>",
                    content_type="text/html",
                    status=400,
                )
            if not code:
                return web.Response(text="<h2>Spotify did not return an authorization code.</h2>", content_type="text/html", status=400)
            self.pending_state = None
            try:
                self.oauth().get_access_token(code, as_dict=True, check_cache=False)
            except Exception:
                log.exception("Spotify OAuth token exchange failed")
                return web.Response(
                    text="<h2>Spotify login failed</h2><p>Check the Client ID, secret, and exact redirect URI, then try /spotifylogin again.</p>",
                    content_type="text/html",
                    status=500,
                )
        log.info("Spotify account authorization completed.")
        return web.Response(
            text="<h2>Spotify connected successfully</h2><p>You can close this tab and return to Discord.</p>",
            content_type="text/html",
        )

    @app_commands.command(name="spotifylogin", description="Link your Spotify Premium account to control your Spotify devices")
    async def spotifylogin(self, interaction: discord.Interaction):
        await self.owner_only(interaction)
        if not CLIENT_ID or not CLIENT_SECRET:
            await interaction.response.send_message("Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in your .env first.", ephemeral=True)
            return
        state = secrets.token_urlsafe(24)
        self.pending_state = state
        url = self.oauth().get_authorize_url(state=state)
        await interaction.response.send_message(
            f"Open this link to securely authorize Spotify, then approve the requested permissions:\n{url}\n\n"
            "After approval, the callback page should say Spotify connected successfully. Do not share the link or your token cache.",
            ephemeral=True,
        )

    @app_commands.command(name="myplaylists", description="List playlists from your linked Spotify account")
    async def myplaylists(self, interaction: discord.Interaction):
        await self.owner_only(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            client = self.spotify()
            result = client.current_user_playlists(limit=50)
            items = result.get("items", [])
            if not items:
                await interaction.followup.send("No playlists were returned. Confirm Spotify is linked and the account has playlists.", ephemeral=True)
                return
            embed = discord.Embed(title="Your Spotify playlists", color=discord.Color.green())
            for item in items[:20]:
                name = discord.utils.escape_markdown(item.get("name", "Untitled playlist"))
                url = item.get("external_urls", {}).get("spotify", "")
                tracks = item.get("tracks", {}).get("total", "?")
                embed.add_field(name=name[:250], value=f"{tracks} tracks · [Open playlist]({url})", inline=False)
            if len(items) > 20:
                embed.set_footer(text="Showing up to 20 playlists from the first page.")
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.exception("Could not list Spotify playlists")
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    @app_commands.command(name="playplaylist", description="Play one of your Spotify playlists on an available Spotify device")
    @app_commands.describe(url="Your Spotify playlist URL", device_id="Optional device ID from /spotifydevices")
    async def playplaylist(self, interaction: discord.Interaction, url: str, device_id: str | None = None):
        await self.owner_only(interaction)
        match = re.search(r"(?:open\.spotify\.com/playlist/|spotify:playlist:)([A-Za-z0-9]+)", url.strip())
        if not match:
            await interaction.response.send_message("Enter a Spotify playlist URL or spotify:playlist: URI.", ephemeral=True)
            return
        playlist_uri = f"spotify:playlist:{match.group(1)}"
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            client = self.spotify()
            if device_id:
                client.start_playback(device_id=device_id, context_uri=playlist_uri)
            else:
                client.start_playback(context_uri=playlist_uri)
            await interaction.followup.send(
                f"Asked Spotify to play [this playlist]({url}) on your active device. If no device is active, open Spotify on a device and try again.",
                ephemeral=True,
            )
        except Exception as exc:
            log.exception("Spotify playlist playback request failed")
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    @app_commands.command(name="spotifydevices", description="Show Spotify Connect devices available to your account")
    async def spotifydevices(self, interaction: discord.Interaction):
        await self.owner_only(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            devices = self.spotify().devices().get("devices", [])
            if not devices:
                await interaction.followup.send("No Spotify devices found. Open Spotify on your phone, computer, or speaker, then run this command again.", ephemeral=True)
                return
            lines = []
            for device in devices[:20]:
                status = "active" if device.get("is_active") else "available"
                restricted = " · restricted" if device.get("is_restricted") else ""
                lines.append(f"**{discord.utils.escape_markdown(device.get('name', 'Spotify device'))}** — {device.get('type', 'device')} · {status}{restricted}\nID: `{device.get('id') or 'unavailable'}`")
            await interaction.followup.send("\n\n".join(lines), ephemeral=True)
        except Exception as exc:
            log.exception("Could not list Spotify devices")
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    @app_commands.command(name="spotifypause", description="Pause playback on your Spotify account")
    async def spotifypause(self, interaction: discord.Interaction):
        await self.owner_only(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            self.spotify().pause_playback()
            await interaction.followup.send("Spotify playback paused.", ephemeral=True)
        except Exception as exc:
            log.exception("Spotify pause failed")
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    @app_commands.command(name="spotifyskip", description="Skip to the next track on your Spotify account")
    async def spotifyskip(self, interaction: discord.Interaction):
        await self.owner_only(interaction)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            self.spotify().next_track()
            await interaction.followup.send("Skipped to the next Spotify track.", ephemeral=True)
        except Exception as exc:
            log.exception("Spotify skip failed")
            await interaction.followup.send(self.error_message(exc), ephemeral=True)

    @staticmethod
    def error_message(exc: Exception) -> str:
        message = str(exc)
        if "No token available" in message or "cache" in message.lower() and "token" in message.lower():
            return "Spotify is not linked yet. Run /spotifylogin first."
        if "NO_ACTIVE_DEVICE" in message or "No active device" in message:
            return "No active Spotify device. Open Spotify on a device, start any track, then retry. Use /spotifydevices to see available devices."
        if "PREMIUM_REQUIRED" in message or "403" in message:
            return "Spotify refused the request. Confirm the account has Premium, the requested permissions were approved, and the device is not restricted."
        if "invalid_grant" in message or "redirect_uri" in message.lower():
            return "Spotify authorization expired or the redirect URI does not match your Spotify Developer Dashboard exactly. Run /spotifylogin again and verify SPOTIFY_REDIRECT_URI."
        return "Spotify request failed. Check the bot terminal logs for details, then try /spotifylogin again if needed."


async def setup(bot: commands.Bot):
    await bot.add_cog(SpotifyAccountCog(bot))
