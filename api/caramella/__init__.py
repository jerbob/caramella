import aioredis

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, UJSONResponse
from starlette.routing import Route


async def scores(request: Request) -> UJSONResponse:
    points = await pool.hgetall('scores', encoding='utf-8')
    scores = [
        {
            'name': await pool.hget('names', _id),
            'score': score,
            'listening': False
        }
        for _id, score in points.items()
        if int(score) > 0
    ]
    scores.sort(key=lambda item: -int(item['score']))
    return UJSONResponse(scores)


async def homepage(request: Request) -> PlainTextResponse:
    return PlainTextResponse('This is not the endpoint you are looking for.')


async def readable(request: Request) -> PlainTextResponse:
    seconds = request.query_params.get('seconds')
    if type(seconds) is not str or not seconds.isnumeric():
        return PlainTextResponse('0 seconds')
    seconds = int(seconds)
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
        return PlainTextResponse(f'{prefix} and {suffix}')
    else:
        return PlainTextResponse(suffix)


app = Starlette(
    routes=[
        Route('/', homepage),
        Route('/scores', scores),
        Route('/readable', readable),
    ]
)


@app.on_event('startup')
async def startup() -> None:
    global pool
    pool = await aioredis.create_redis_pool('redis://redis')
