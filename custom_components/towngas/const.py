"""Constants for the Towngas integration."""

DOMAIN = "towngas"

CONF_API_URL = "api_url"
CONF_ACCOUNT_ID = "account_id"
CONF_AUTHORIZATION = "authorization"
CONF_UPDATE_INTERVAL = "update_interval"

DEFAULT_API_URL = "https://rqjf.jnyuxia.com"
DEFAULT_UPDATE_INTERVAL = 30
MIN_UPDATE_INTERVAL = 5
MAX_UPDATE_INTERVAL = 1440
HISTORY_ATTRIBUTE_LIMIT = 24

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "towngas.history"

# v1 keys are retained only for one-time config-entry/entity migration.
LEGACY_CONF_HOST = "host"
LEGACY_CONF_ORG_CODE = "orgCode"
LEGACY_CONF_SUBS_CODE = "subsCode"
LEGACY_CONF_UPDATE_INTERVAL = "updatetime"
LEGACY_CONF_MINI_API_URL = "mini_api_url"
LEGACY_CONF_MINI_ACCOUNT_ID = "mini_account_id"
LEGACY_CONF_MINI_API_TOKEN = "mini_api_token"
