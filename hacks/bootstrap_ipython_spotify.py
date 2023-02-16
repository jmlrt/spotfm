"""Script to load in iPython to bootstrap the resources required to work with the spotify module
"""

import logging

from hacks import manage_db  # noqa: F401
from spotfm import spotify, utils

logging.getLogger().setLevel(logging.INFO)
config = utils.parse_config()
sp = spotify.Client(config["spotify"]["client_id"], config["spotify"]["client_secret"])
