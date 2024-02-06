"""Constants for the quieromudarme package."""

from typing import Final

import pytz

EXCESSIVE_RESULTS_WARNING: Final = 200
EXCESSIVE_RESULTS_ERROR: Final = 500
MAX_NOTIFS_IN_UPDATE_PER_USER: Final = 5

# Make sure these are the same as in dbschema/default.esdl
MAX_FREE_SEARCHES: Final = 2
PRICE_OFF_PCT_THRESHOLD: Final = 0.05

# Timezone of users and of providers
LOCAL_TZ: Final = pytz.timezone("America/Argentina/Buenos_Aires")
