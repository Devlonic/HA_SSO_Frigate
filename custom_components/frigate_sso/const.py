"""Constants for the Frigate SSO bridge."""

DOMAIN = "frigate_sso"
VERSION = "1.0.0"

CONF_URL = "url"
CONF_START_PATH = "start_path"
CONF_COOKIE_DOMAIN = "cookie_domain"
CONF_COOKIE_NAME = "cookie_name"
CONF_JWT_SECRET_FILE = "jwt_secret_file"
CONF_ADMIN_ROLE = "admin_role"
CONF_DEFAULT_ROLE = "default_role"
CONF_USER_ROLES = "user_roles"
CONF_TOKEN_TTL = "token_ttl"
CONF_RENEW_INTERVAL = "renew_interval"
CONF_SIDEBAR_TITLE = "sidebar_title"
CONF_SIDEBAR_ICON = "sidebar_icon"
CONF_PANEL_PATH = "panel_path"

DEFAULT_START_PATH = "/"
DEFAULT_COOKIE_NAME = "frigate_token"  # must match Frigate auth.cookie_name
DEFAULT_ADMIN_ROLE = "admin"
DEFAULT_ROLE = "viewer"
# Frigate tries to refresh a cookie once it is within auth.refresh_time (1800 s)
# of expiry, and that refresh fails for users that are not in Frigate's DB.
# So a token is usable for (token_ttl - 1800) s; the panel renews well before.
DEFAULT_TOKEN_TTL = 3600
DEFAULT_RENEW_INTERVAL = 600
DEFAULT_SIDEBAR_TITLE = "Frigate"
DEFAULT_SIDEBAR_ICON = "mdi:cctv"
DEFAULT_PANEL_PATH = "frigate"

API_URL = "/api/frigate_sso/session"
PANEL_STATIC_URL = "/frigate_sso_static/frigate-sso-panel.js"
PANEL_WEBCOMPONENT = "frigate-sso-panel"
PANEL_FILENAME = "frigate-sso-panel.js"
