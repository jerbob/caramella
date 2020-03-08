"""Utility methods for the main client."""

from dataclasses import dataclass
from typing import Any, Union

from discord import FFmpegOpusAudio, Member, VoiceChannel
from discord.ext.commands import Context


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
        before_options='-stream_loop -1 -ss 00:00'
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
