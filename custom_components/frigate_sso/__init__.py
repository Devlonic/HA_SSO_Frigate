"""Frigate SSO: turn a Home Assistant session into a Frigate session.

Home Assistant mints a Frigate-compatible JWT (HS256, signed with Frigate's
.jwt_secret) for the logged-in HA user and stores it as the Frigate auth cookie
on the shared parent domain, so a Frigate iframe on a sibling subdomain is
authenticated without a second login. Frigate validates the token natively.
"""

from __future__ import annotations

import logging
import os
import re
import time

from aiohttp import web
import jwt
import voluptuous as vol

from homeassistant.auth.models import User
from homeassistant.components import panel_custom
from homeassistant.components.http import (
    KEY_HASS_USER,
    HomeAssistantView,
    StaticPathConfig,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    API_URL,
    CONF_ADMIN_ROLE,
    CONF_COOKIE_DOMAIN,
    CONF_COOKIE_NAME,
    CONF_DEFAULT_ROLE,
    CONF_JWT_SECRET_FILE,
    CONF_PANEL_PATH,
    CONF_RENEW_INTERVAL,
    CONF_SIDEBAR_ICON,
    CONF_SIDEBAR_TITLE,
    CONF_START_PATH,
    CONF_TOKEN_TTL,
    CONF_URL,
    CONF_USER_ROLES,
    DEFAULT_ADMIN_ROLE,
    DEFAULT_COOKIE_NAME,
    DEFAULT_PANEL_PATH,
    DEFAULT_RENEW_INTERVAL,
    DEFAULT_ROLE,
    DEFAULT_SIDEBAR_ICON,
    DEFAULT_SIDEBAR_TITLE,
    DEFAULT_START_PATH,
    DEFAULT_TOKEN_TTL,
    DOMAIN,
    PANEL_FILENAME,
    PANEL_STATIC_URL,
    PANEL_WEBCOMPONENT,
    VERSION,
)

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_URL): cv.url,
                vol.Required(CONF_COOKIE_DOMAIN): cv.string,
                vol.Required(CONF_JWT_SECRET_FILE): cv.string,
                vol.Optional(CONF_START_PATH, default=DEFAULT_START_PATH): cv.string,
                vol.Optional(CONF_COOKIE_NAME, default=DEFAULT_COOKIE_NAME): cv.string,
                vol.Optional(CONF_ADMIN_ROLE, default=DEFAULT_ADMIN_ROLE): cv.string,
                vol.Optional(CONF_DEFAULT_ROLE, default=DEFAULT_ROLE): cv.string,
                vol.Optional(CONF_USER_ROLES, default={}): {cv.string: cv.string},
                vol.Optional(CONF_TOKEN_TTL, default=DEFAULT_TOKEN_TTL): vol.All(
                    vol.Coerce(int), vol.Range(min=1900)
                ),
                vol.Optional(
                    CONF_RENEW_INTERVAL, default=DEFAULT_RENEW_INTERVAL
                ): vol.All(vol.Coerce(int), vol.Range(min=60)),
                vol.Optional(
                    CONF_SIDEBAR_TITLE, default=DEFAULT_SIDEBAR_TITLE
                ): cv.string,
                vol.Optional(CONF_SIDEBAR_ICON, default=DEFAULT_SIDEBAR_ICON): cv.icon,
                vol.Optional(CONF_PANEL_PATH, default=DEFAULT_PANEL_PATH): cv.slug,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def _read_signing_key(path: str) -> bytes:
    """Read Frigate's JWT secret and derive the key the same way Frigate does.

    Mirrors frigate/api/fastapi_app.py: an even-length hex secret (the format
    Frigate generates) is used as raw bytes, anything else as UTF-8.
    """
    with open(path, encoding="utf-8") as file:
        secret = file.readline().strip()
    if not secret:
        raise ValueError(f"{path} is empty")
    if len(secret) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", secret):
        return bytes.fromhex(secret)
    return secret.encode("utf-8")


def _frigate_username(user: User) -> str:
    """Prefer the HA login name; fall back to the display name, then the id."""
    for credential in user.credentials:
        if username := credential.data.get("username"):
            return str(username)
    return user.name or user.id


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Frigate SSO bridge from YAML."""
    conf = config[DOMAIN]

    try:
        key = await hass.async_add_executor_job(
            _read_signing_key, conf[CONF_JWT_SECRET_FILE]
        )
    except (OSError, ValueError) as err:
        _LOGGER.error("Cannot read Frigate JWT secret: %s", err)
        return False

    url = conf[CONF_URL].rstrip("/")
    # No trailing slash: Frigate's UI loads translations from the relative path
    # "locales/...", so "/explore/" would fetch "/explore/locales/..." (index.html)
    # and render raw translation keys instead of text.
    start_path = "/" + conf[CONF_START_PATH].strip("/")
    cookie_domain = conf[CONF_COOKIE_DOMAIN].lstrip(".").lower()

    hass.http.register_view(FrigateSsoSessionView(conf, key, url, start_path))

    panel_file = os.path.join(os.path.dirname(__file__), "frontend", PANEL_FILENAME)
    try:
        cache_bust = int(
            await hass.async_add_executor_job(os.path.getmtime, panel_file)
        )
    except OSError:
        cache_bust = 0

    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_URL, panel_file, cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=conf[CONF_PANEL_PATH],
        webcomponent_name=PANEL_WEBCOMPONENT,
        module_url=f"{PANEL_STATIC_URL}?v={VERSION}&m={cache_bust}",
        sidebar_title=conf[CONF_SIDEBAR_TITLE],
        sidebar_icon=conf[CONF_SIDEBAR_ICON],
        require_admin=False,
        config={
            "url": url,
            "start_path": start_path,
            "cookie_domain": cookie_domain,
            "renew_interval": conf[CONF_RENEW_INTERVAL],
            "token_ttl": conf[CONF_TOKEN_TTL],
        },
    )
    return True


class FrigateSsoSessionView(HomeAssistantView):
    """Issue a Frigate session cookie for the authenticated HA user."""

    url = API_URL
    name = "api:frigate_sso:session"
    requires_auth = True

    def __init__(self, conf: ConfigType, key: bytes, url: str, start_path: str) -> None:
        """Store the configuration."""
        self._conf = conf
        self._key = key
        self._url = url
        self._start_path = start_path
        self._cookie_domain = conf[CONF_COOKIE_DOMAIN].lstrip(".").lower()

    def _role_for(self, user: User, username: str) -> str:
        if (role := self._conf[CONF_USER_ROLES].get(username)) is not None:
            return role
        if user.is_admin:
            return self._conf[CONF_ADMIN_ROLE]
        return self._conf[CONF_DEFAULT_ROLE]

    async def post(self, request: web.Request) -> web.Response:
        """Mint a Frigate JWT and set it as a cookie on the shared domain."""
        user: User = request[KEY_HASS_USER]
        if user.system_generated or not user.is_active:
            return self.json_message("User not allowed", 403)

        username = _frigate_username(user)
        role = self._role_for(user, username)
        now = int(time.time())
        ttl = self._conf[CONF_TOKEN_TTL]
        token = jwt.encode(
            {"sub": username, "role": role, "iat": now, "exp": now + ttl},
            self._key,
            algorithm="HS256",
        )

        response = self.json(
            {
                "url": self._url,
                "start_path": self._start_path,
                "cookie_domain": self._cookie_domain,
                "username": username,
                "role": role,
                "expires_in": ttl,
                "renew_interval": self._conf[CONF_RENEW_INTERVAL],
            }
        )
        response.set_cookie(
            self._conf[CONF_COOKIE_NAME],
            token,
            domain=self._cookie_domain,
            path="/",
            max_age=ttl,
            secure=True,
            httponly=True,
            samesite="Lax",
        )
        response.headers["Cache-Control"] = "no-store"
        _LOGGER.debug("Issued Frigate session for %s (role %s)", username, role)
        return response
