"""Constants for use in the client."""

from os import getenv

from dotenv import load_dotenv


load_dotenv()

TOKEN = getenv('CARAMELLA_TOKEN')
