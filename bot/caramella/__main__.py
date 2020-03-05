import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from time import time
from typing import Any, AsyncGenerator, Dict, Union

import aiosqlite

from caramella import constants

from discord.utils import get as discord_get
from discord import (
    Colour, Embed, FFmpegOpusAudio, Role, Game, Member, VoiceChannel, VoiceClient, VoiceState
)
from discord.ext import tasks
from discord.ext.commands import Bot, Cog, CommandError, Context, check, command, when_mentioned_or


with sqlite3.connect('points.db') as connection:
    connection.execute(
        'CREATE TABLE IF NOT EXISTS points ('
        '    id INTEGER PRIMARY KEY,'
        '    points INTEGER NOT NULL'
        ')'
    )
    connection.commit()


async def update_points(member: Member, seconds: int) -> None:
    """Add a specified number of points to a user's score."""
    async with aiosqlite.connect('points.db') as db:
        cursor = await db.execute('SELECT points FROM points WHERE id=?', (member.id,))
        score = await cursor.fetchone() or (0,)
        await cursor.close()
        seconds += sum(score)
        await db.execute('REPLACE INTO points (id, points) VALUES(?, ?)', (member.id, seconds))
        await db.commit()


async def leaderboard() -> AsyncGenerator:
    """Yield the current leaderboard."""
    async with aiosqlite.connect('points.db') as db:
        async with db.execute(
            'SELECT id, points FROM points'
            ' ORDER BY points DESC'
            ' LIMIT 10'
        ) as cursor:
            async for row in cursor:
                yield row


async def is_danser(ctx: Context) -> bool:
    """Check if the author is Aperture or Table."""
    return ctx.author.id in (
        172533414363136001, 140605665772175361
    )


def get_readable_string(seconds: int) -> str:
    """Return a readable representation of a number of seconds."""
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    measures = dict(day=days, hour=hours, minute=minutes, second=seconds)
    segments = [
        f'{value:,} {name}{"s" if value > 1 else ""}'
        for name, value in measures.items()
        if value
    ]
    if not segments:
        return '0 seconds'
    prefix, suffix = ', '.join(segments[:-1]), segments[-1]
    if prefix:
        return f'{prefix} and {suffix}'
    else:
        return suffix


@dataclass
class Player:
    target: Union[Member, VoiceChannel]

    tempo = 1.0
    seconds = 0.0
    source = FFmpegOpusAudio(
        'caramelldansen.opus',
        before_options=f'-stream_loop -1 -ss 00:00'
    )

    @property
    def seek(self) -> str:
        """Return a string representing a time to seek to."""
        return str(round(self.seconds % 175, 1))

    @property
    def tempo_filter(self) -> str:
        """Return a string representing the tempo filter."""
        if 0.5 <= self.tempo <= 2:
            return f'atempo={self.tempo}'
        elif self.tempo < 0.5:
            ratio = round(self.tempo / 0.5, 2)
            return f'atempo=0.5,atempo={ratio}'
        else:
            ratio = round(self.tempo / 2, 2)
            return f'atempo=2.0,atempo={ratio}'

    def reload(self) -> Any:
        """Reload the internal AudioSource."""
        self.source = FFmpegOpusAudio(
            'caramelldansen.opus',
            before_options=f'-stream_loop -1 -ss {self.seek}',
            options=f'-filter:a "{self.tempo_filter}"'
        )


class Music(Cog):
    def __init__(self, bot: Bot) -> None:
        """Set all options to their initial values."""
        self.bot = bot
        self.timestamps: dict = {}
        self.players: Dict[int, Player] = {}
        self.background_task.start()

    @command()
    @check(is_danser)
    async def target(self, ctx: Context, target: Union[Member, VoiceChannel]) -> Any:
        """Target a particular user or channel."""
        if (player := self.players.get(ctx.guild.id)):
            player.target = target
        else:
            self.players[ctx.guild.id] = Player(target)
        voice_client = target.guild.voice_client
        current = getattr(voice_client, 'channel', None)
        if type(target) is Member and target.voice and not target.bot:
            if target.voice.channel and target.voice.channel != current:
                await self.join_continue_player(target.voice.channel)
        elif type(target) is VoiceChannel:
            if current != target:
                if voice_client:
                    await self.save_quit_player(voice_client)
                if len(target.members) > 0:
                    await self.join_continue_player(target)

    @command()
    async def join(self, ctx: Context) -> Any:
        """Join the user's voice channel."""
        self.players[ctx.guild.id] = Player(ctx.author.voice.channel)
        await ctx.voice_client.disconnect()
        await ctx.author.voice.channel.connect()

    @command()
    async def speed(self, ctx: Context, tempo: float) -> Any:
        """Change the tempo of the stream."""
        if not 0.25 <= tempo <= 4.0:
            return await ctx.send('Speed must be between `0.25` and `4.0`')
        else:
            self.tempo = tempo

    @command()
    async def leaderboard(self, ctx: Context) -> Any:
        """Display a leaderboard of top 10 players."""
        async with ctx.channel.typing():
            for client in self.bot.voice_clients:
                for member in client.channel.members:
                    if all((
                        not member.bot,
                        member.id in self.timestamps
                    )):
                        points = int(time() - self.timestamps[member.id])
                        self.timestamps[member.id] = time()
                        await update_points(member, points)
            embed = Embed(colour=Colour(0x8b0000))
            async for (_id, score) in leaderboard():
                user = self.bot.get_user(_id)
                embed.add_field(
                    name=f'{user.name}#{user.discriminator}',
                    value=get_readable_string(score),
                    inline=False
                )
        await ctx.send(embed=embed)

    @command()
    async def stats(self, ctx: Context, member: Member = None) -> Any:
        """Show statistics for a specific member."""
        if member is None:
            member = ctx.author
        async with ctx.channel.typing():
            if all((
                not member.bot,
                member.id in self.timestamps
            )):
                points = int(time() - self.timestamps[member.id])
                self.timestamps[member.id] = time()
                await update_points(member, points)
            async with aiosqlite.connect('points.db') as db:
                cursor = await db.execute('SELECT points FROM points WHERE id=?', (member.id,))
                score = await cursor.fetchone() or (0,)
                await cursor.close()
            embed = Embed(colour=Colour(0x8b0000))
            for points in score:
                user = self.bot.get_user(member.id)
                embed.add_field(
                    name=f'{user.name}#{user.discriminator}',
                    value=get_readable_string(points),
                    inline=False
                )
        await ctx.send(embed=embed)

    @join.before_invoke
    @speed.before_invoke
    async def prepare_player(self, ctx: Context) -> Any:
        """Ensure that the user can run these commands."""
        if ctx.voice_client is None:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
            else:
                return await ctx.send("You are not connected to a voice channel!")
                raise CommandError("User is not connected to a voice channel.")
        elif ctx.voice_client.is_playing():
            self.players[ctx.guild.id].seconds = time() - ctx.voice_client.started
            ctx.voice_client.stop()

    @join.after_invoke
    @speed.after_invoke
    async def restart_player(self, ctx: Context) -> Any:
        """Restart the player after option changes."""
        player = self.players[ctx.guild.id]
        player.reload()
        if ctx.voice_client:
            ctx.voice_client.play(player.source)
            ctx.voice_client.started = time()

    async def save_quit_player(self, voice_client: VoiceClient, guild_id: int) -> None:
        """Save the current position and disconnect from voice."""
        player = self.players[guild_id]
        player.seconds = time() - getattr(voice_client, 'started', time())
        await voice_client.disconnect()

    async def join_continue_player(self, channel: VoiceChannel) -> None:
        """Connect to a voice channel and seek to the last bookmark."""
        player = self.players.get(channel.guild.id)
        if not player:
            player = Player(channel)
            self.players[channel.guild.id] = player
        voice_client = await channel.connect()
        player.reload()
        voice_client.play(player.source)
        voice_client.started = time()

    @Cog.listener()
    async def on_voice_state_update(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState
    ) -> None:
        """Update points and state, depending on the current target."""
        player = self.players.get(member.guild.id)
        target = player.target if player else None
        voice_client = member.guild.voice_client
        current_channel = getattr(voice_client, 'channel', None)
        if target == member:
            if voice_client:
                if after.channel != voice_client.channel:
                    await self.save_quit_player(voice_client, member.guild.id)
            if after.channel:
                await self.join_continue_player(after.channel)
        elif type(target) is VoiceChannel:
            if voice_client is None or voice_client.channel != after.channel:
                if before.channel == target and len(before.channel.members) == 1:
                    await self.save_quit_player(voice_client, member.guild.id)
                elif after.channel == target and len(after.channel.members) > 0:
                    await self.join_continue_player(after.channel)
        if not member.bot:
            stopped_listening = any((
                after.self_deaf and not before.self_deaf,
                after.channel != before.channel == current_channel
            ))
            started_listening = (current_channel == after.channel) and any((
                before.self_deaf and not after.self_deaf,
                before.channel != current_channel and not after.self_deaf
            ))
            if stopped_listening and member.id in self.timestamps:
                print(f'{member} stopped listening!')
                points = int(time() - self.timestamps[member.id])
                del self.timestamps[member.id]
                await update_points(member, points)
            if started_listening:
                print(f'{member} started listening!')
                self.timestamps[member.id] = time()
        else:
            for member in (after.channel.members if after.channel else ()):
                if member != self.bot.user:
                    print(f'{member} started listening!')
                    self.timestamps[member.id] = time()
            for member in (before.channel.members if before.channel else ()):
                if not member.bot:
                    if member.id in self.timestamps:
                        print(f'{member} stopped listening!')
                        points = int(time() - self.timestamps[member.id])
                        del self.timestamps[member.id]
                        await update_points(member, points)

    @tasks.loop(minutes=1)
    async def background_task(self):
        """Recheck user roles in the Caramella Crew Discord."""

        print('[?] Updating listeners...')

        listeners = 0
        for client in self.bot.voice_clients:
            if client.channel:
                for member in client.channel.members:
                    if not member.bot:
                        listeners += 1

        await bot.change_presence(
            activity=(
                Game(f'for 1 dancer') if listeners == 1
                else Game(f'for {listeners} dancers')
            )
        )

        print('Updating roles...')
        role_list = {
            0: 'unenlightened',
            600: 'Caramella Babies - 10 Minutes',
            3600: 'Caramella Fans - 1 Hour',
            43200: 'Caramella Captains - 12 Hours',
            86400: 'Caramella Dancers - 1 Day'
        }
        for amount, name in role_list.items():
            for role in self.caramella_crew.roles:
                if role.name == name:
                    role_list[amount] = role
                    break

        scoreboard = []
        async with aiosqlite.connect('points.db') as db:
            async with db.execute('SELECT id, points FROM points') as cursor:
                async for row in cursor:
                    scoreboard.append(row)

        for _id, points in scoreboard:
            roles = []
            member = self.caramella_crew.get_member(_id)
            if not member:
                continue
            for amount, role in role_list.items():
                roles.append(role)
                if amount > points:
                    break
            if len(roles) >= 3:
                *old_roles, correct_role, _ = roles
            else:
                *old_roles, correct_role = roles
            for role in old_roles:
                if role in member.roles:
                    await member.remove_roles(role)
            if correct_role not in member.roles:
                await member.add_roles(correct_role)
            roles.clear()

        print('Roles updated!')

    @background_task.before_loop
    async def ensure_bot_available(self):
        print('Waiting for bot to become available...')
        await self.bot.wait_until_ready()
        self.caramella_crew = self.bot.get_guild(684524607889473584)


bot = Bot(command_prefix=when_mentioned_or('caramella ', '!'))


@bot.event
async def on_ready():
    print(f'Logged in as: {bot.user.name} - {bot.user.id}')


bot.add_cog(Music(bot))
bot.run(constants.TOKEN)
