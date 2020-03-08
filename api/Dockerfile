FROM python:3.8-alpine
ENV PYTHONUNBUFFERED 1

RUN mkdir /code/
WORKDIR /code/
ADD . /code/

EXPOSE 8000

RUN apk add --no-cache --virtual .build-deps \
    ca-certificates gcc linux-headers musl-dev \
    libffi-dev make

RUN pip install -r requirements.txt

CMD ["uvicorn", "caramella:app", "--host", "0.0.0.0"]
