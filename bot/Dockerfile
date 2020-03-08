FROM python:3.8-alpine
ENV PYTHONUNBUFFERED 1

RUN mkdir /code/
WORKDIR /code/
ADD . /code/

RUN apk add --no-cache --virtual .build-deps \
    ca-certificates gcc linux-headers musl-dev \
    libffi-dev make ffmpeg

RUN pip install -r requirements.txt

CMD ["python", "-m", "caramella"]
