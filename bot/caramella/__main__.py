from json import dumps
from time import time
from typing import Any, AsyncGenerator, Dict, Union

import aioredis

from caramella import constants
from caramella.utils import Player, get_readable_string, is_danser

from discord import (
    Colour, Embed, Game, Member, VoiceChannel, VoiceClient, VoiceState
)
from discord.ext import tasks
from discord.ext.commands import (
    Bot, Cog, CommandError, Context, check, command, when_mentioned_or
)
from discord.utils import get as discord_get


class Music(Cog):
    def __init__(self, bot: Bot) -> None:
        """Set all options to their initial values."""
        self.bot = bot
        self.timestamps: dict = {}
        self.players: Dict[int, Player] = {}
        self.update_roles.start()
        self.update_redis.start()
        self.update_listeners.start()

    async def update_points(self, member: Member, seconds: int) -> None:
        """Add a specified number of points to a user's scores."""
        await self.bot.pool.hsetnx('scores', member.id, 0)
        score = await self.bot.pool.hget('scores', member.id)
        seconds += int(score)
        await self.bot.pool.hset('scores', member.id, seconds)
        await self.bot.pool.hsetnx('names', member.id, str(member))
        # Publish to the site's websocket event
        await self.bot.pool.publish('channel:score', dumps({
            'member': member.id,
            'score': seconds
        }))

    async def _leaderboard(self) -> AsyncGenerator:
        """Yield the current leaderboard."""
        scores = await self.bot.pool.hgetall('scores', encoding='utf-8')
        scores = sorted(scores.items(), key=lambda pair: -int(pair[1]))
        for score in scores[:10]:
            yield score

    @command()
    @check(is_danser)
    async def target(self, ctx: Context, target: Union[Member, VoiceChannel]) -> Any:
        """Target  particular user or channel."""
        if player := self.players.get(ctx.guild.id):
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
        if ctx.voice_client and ctx.voice_client.channel == ctx.author.voice.channel:
            return
        await ctx.author.voice.channel.connect()
        self.players[ctx.guild.id] = Player(ctx.author.voice.channel)

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
                        await self.update_points(member, points)
            embed = Embed(colour=Colour(0x8b0000))
            async for (_id, score) in self._leaderboard():
                if user := self.bot.get_user(int(_id)):
                    embed.add_field(
                        name=str(user),
                        value=get_readable_string(int(score)),
                        inline=False
                    )
        await ctx.send(embed=embed)

    @command()
    async def stats(self, ctx: Context, member: Member = None) -> Any:
        """Show statistics for a specific member."""
        if member is None:
            member = ctx.author
        async with ctx.channel.typing():
            if not member.bot and self.is_listening(member):
                points = int(time() - self.timestamps[member.id])
                self.timestamps[member.id] = time()
                await self.update_points(member, points)
            await self.bot.pool.hsetnx('scores', member.id, 0)
            score = await self.bot.pool.hget('scores', member.id)
            embed = Embed(colour=Colour(0x8b0000))
            user = self.bot.get_user(member.id)
            embed.add_field(
                name=f'{user.name}#{user.discriminator}',
                value=get_readable_string(int(score)),
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
        elif ctx.author.voice and ctx.author.voice.channel != ctx.voice_client.channel:
            await self.save_quit_player(ctx.voice_client, ctx.guild.id)
            await self.join_continue_player(ctx.author.voice.channel)
        elif ctx.voice_client.is_playing():
            self.players[ctx.guild.id].seconds = time() - ctx.voice_client.started
            ctx.voice_client.stop()

    @join.after_invoke
    @speed.after_invoke
    async def restart_player(self, ctx: Context) -> Any:
        """Restart the player after option changes."""
        player = self.players.get(ctx.guild.id)
        if player:
            player.reload()
        if ctx.voice_client:
            player = Player(ctx.voice_client.channel)
            player.reload()
            self.players[ctx.guild.id] = player
            ctx.voice_client.play(player.source)
            ctx.voice_client.started = time()

    async def save_quit_player(self, voice_client: VoiceClient, guild_id: int) -> None:
        """Save the current position and disconnect from voice."""
        print(f'[?] Leaving {voice_client.channel}...')
        player = self.players[guild_id]
        player.seconds = time() - getattr(voice_client, 'started', time())
        await voice_client.disconnect()

    async def join_continue_player(self, channel: VoiceChannel) -> None:
        """Connect to a voice channel and seek to the last bookmark."""
        voice_client = channel.guild.voice_client
        print(f'[?] Joining {channel}...')
        if not voice_client or voice_client.channel != channel:
            if voice_client:
                await voice_client.disconnect()
            player = self.players.get(channel.guild.id)
            if not player:
                player = Player(channel)
                self.players[channel.guild.id] = player
            voice_client = await channel.connect()
            player.reload()
            voice_client.play(player.source)
            voice_client.started = time()

    async def start_listening(self, member: Member, update: bool = True) -> None:
        """Start a user's score counter."""
        print(f'{member} started listening!')
        self.timestamps[member.id] = time()
        print(self.timestamps)
        if update:
            await self.bot.pool.publish('channel:score', dumps({
                'member': member.id,
                'listening': True
            }))

    async def stop_listening(self, member: Member, update: bool = True) -> None:
        """Stop a user's score counter."""
        if not self.timestamps.get(member.id):
            return
        points = int(time() - self.timestamps[member.id])
        await self.update_points(member, points)
        if update:
            print(f'{member} stopped listening!')
            del self.timestamps[member.id]
            print(self.timestamps)

    def is_listening(self, member: Member) -> None:
        """Check if a member is currently listening to Caramella."""
        return member == self.bot.user or member.id in self.timestamps

    @Cog.listener()
    async def on_voice_state_update(
        self,
        member: Member,
        before: VoiceState,
        after: VoiceState
    ) -> None:
        """Update points and state, depending on the current target."""
        if member.bot and member != self.bot.user:
            # Member is another bot
            return
        player = self.players.get(member.guild.id)
        target = player.target if player else 0
        voice_client = member.guild.voice_client

        # Get the bot's current voice client
        current_channel = getattr(voice_client, 'channel', 0)

        if target == member:
            if voice_client and after.channel != current_channel:
                # Target left the bot's channel
                await self.save_quit_player(voice_client, member.guild.id)

            if after.channel and current_channel != after.channel:
                # Target is in a channel that the bot isn't in
                await self.join_continue_player(after.channel)

        if after.channel != before.channel == target and len(before.channel.members) == 1:
            # Target channel lost all listeners :(
            await self.save_quit_player(voice_client, member.guild.id)

        elif before.channel != after.channel == target and len(after.channel.members) > 0:
            # Target channel has users!
            await self.join_continue_player(after.channel)

        # Get the bot's updated voice client
        current_channel = getattr(voice_client, 'channel', 0)

        if not member.bot:
            # Only watch for normal user accounts
            stopped_listening = any((
                after.self_deaf and not before.self_deaf,
                after.channel != before.channel == current_channel
            ))
            started_listening = (current_channel == after.channel) and any((
                before.self_deaf and not after.self_deaf,
                (before.channel != current_channel) and not after.self_deaf
            ))
            if stopped_listening and not before.self_deaf:
                await self.stop_listening(member)
            elif started_listening and not after.self_deaf:
                await self.start_listening(member)

        elif self.bot.user == member and after.channel != before.channel:
            # The bot changed voice channels
            for member in (before.channel.members if before.channel else ()):
                # Iterate bot's previous channel
                if self.is_listening(member) and not member.voice.self_deaf:
                    await self.stop_listening(member)
            for member in (after.channel.members if after.channel else ()):
                # Iterate bot's current channel
                if not self.is_listening(member) and not member.voice.self_deaf:
                    await self.start_listening(member)

    @tasks.loop(seconds=10)
    async def update_redis(self) -> None:
        """Update current scores and save to the database."""
        for client in self.bot.voice_clients:
            for member in client.channel.members:
                if self.is_listening(member):
                    print('arg')
                    await self.stop_listening(member, update=False)
        await self.bot.pool.bgsave()

    @tasks.loop(seconds=5)
    async def update_listeners(self) -> None:
        """Update the number of currently listening users."""
        listeners = 0
        for client in self.bot.voice_clients:
            if client.channel:
                listeners += len(client.channel.members) - 1

        await self.bot.change_presence(
            activity=(Game(
                'caramelldansen' if listeners == 0 else
                'for 1 dancer' if listeners == 1 else
                f'for {listeners} dancers'
            ))
        )

    @tasks.loop(seconds=30)
    async def update_roles(self) -> None:
        """Recheck user roles in the Caramella Crew Discord."""
        print('Updating roles...')

        scoreboard = await self.bot.pool.hgetall('scores', encoding='utf-8')
        for _id, points in scoreboard.items():
            roles = []
            member = self.caramella_crew.get_member(_id)
            if not member:
                continue
            for amount, role in self.role_list.items():
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

    @update_listeners.before_loop
    async def wait_until_ready(self) -> None:
        """Stall listener updates until the bot is ready."""
        print('Waiting for bot to become available...')
        await self.bot.wait_until_ready()

    @update_roles.before_loop
    async def cache_roles(self) -> None:
        """Store target scores and corresponding role objects."""
        print('Waiting for bot to become available...')
        await self.bot.wait_until_ready()
        self.caramella_crew = self.bot.get_guild(684524607889473584)
        role_list = {
            0: 'unenlightened',
            600: 'Caramella Babies - 10 Minutes',
            3600: 'Caramella Fans - 1 Hour',
            43200: 'Caramella Captains - 12 Hours',
            86400: 'Caramella Dancers - 1 Day'
        }
        for amount, name in role_list.items():
            role_list[amount] = discord_get(self.caramella_crew.roles, name=name)
        self.role_list = role_list


bot = Bot(command_prefix=when_mentioned_or('caramella ', '!'))


@bot.event
async def on_ready() -> None:
    print(f'Logged in as: {bot.user.name} - {bot.user.id}')
    bot.pool = await aioredis.create_redis_pool('redis://redis')


bot.add_cog(Music(bot))
bot.run(constants.TOKEN)
