# Frigate SSO for Home Assistant

Single sign-on from Home Assistant to [Frigate](https://frigate.video). A user logged in to
Home Assistant opens Frigate from the sidebar, embedded in an iframe, with no second login.
Their Frigate role is derived from their Home Assistant permissions.

Nothing changes in Frigate or in your reverse proxy: Frigate validates the session with its
own built-in JWT authentication.

## How it works

1. The integration adds a sidebar panel and an authenticated endpoint,
   `POST /api/frigate_sso/session`.
2. When the panel opens, it calls that endpoint with the user's Home Assistant session.
3. Home Assistant signs a Frigate-compatible JWT with Frigate's own `.jwt_secret`. The token
   is HS256 with the claims `sub`, `role`, `iat` and `exp`.
4. Home Assistant returns the token as Frigate's auth cookie (`frigate_token`), set on the
   parent domain shared by both hosts. The cookie is `Secure`, `HttpOnly` and
   `SameSite=Lax`, and the token never reaches JavaScript.
5. The panel then loads Frigate in an iframe. The iframe is same-site, so the browser sends
   the cookie and Frigate accepts it.
6. While the panel is open it renews the cookie every `renew_interval` seconds, and again
   when the tab becomes visible.

## Requirements

- Home Assistant 2024.7 or newer, and Frigate with authentication enabled. Tested with
  Home Assistant 2026.2 and Frigate 0.17.
- Both hosts are served over HTTPS under the same registrable domain, for example
  `ha.example.com` and `frigate.example.com`, or `example.com` and `frigate.example.com`.
- Frigate is reached through its authenticated port (8971), not the unauthenticated
  port 5000.
- Home Assistant can read Frigate's `.jwt_secret` file, which lives in Frigate's config
  directory.
- Users open Home Assistant through that domain. The panel shows a hint instead of Frigate
  when Home Assistant is opened by IP address or by another hostname, because the cookie
  cannot be set there.

## Installation

1. Copy `custom_components/frigate_sso` into your Home Assistant `config/custom_components/`.
   Alternatively, add this repository to HACS as a custom repository of type *Integration*.
2. Make Frigate's JWT secret readable by Home Assistant. With Docker Compose:

   ```yaml
   services:
     homeassistant:
       volumes:
         - ./frigate/.jwt_secret:/run/frigate_jwt_secret:ro
   ```

   Frigate creates `.jwt_secret` in its config directory on first start. If you set the
   secret through `FRIGATE_JWT_SECRET` instead, put the same value in a file.
3. Add the configuration below to `configuration.yaml` and restart Home Assistant.

## Configuration

```yaml
frigate_sso:
  url: https://frigate.example.com
  cookie_domain: example.com
  jwt_secret_file: /run/frigate_jwt_secret
  start_path: /review        # no trailing slash, see Notes
  admin_role: admin          # Frigate role for Home Assistant administrators
  default_role: viewer       # Frigate role for all other users
  user_roles:                # optional per-login overrides (Home Assistant username -> Frigate role)
    alice: admin
    bob: viewer
```

| Option | Default | Description |
| --- | --- | --- |
| `url` | required | Public Frigate URL that is loaded in the iframe. |
| `cookie_domain` | required | Domain the cookie is set on. It must be the domain Home Assistant is served from, or a parent of it, and must cover Frigate's host. |
| `jwt_secret_file` | required | Path to Frigate's JWT secret inside the Home Assistant container. |
| `start_path` | `/` | Frigate page that is opened first. |
| `admin_role` | `admin` | Frigate role given to Home Assistant administrators. |
| `default_role` | `viewer` | Frigate role given to everyone else. |
| `user_roles` | `{}` | Per-user overrides, keyed by Home Assistant login name. |
| `cookie_name` | `frigate_token` | Must match Frigate's `auth.cookie_name`. |
| `token_ttl` | `3600` | Token lifetime in seconds. Must exceed Frigate's `auth.refresh_time` (default 1800). |
| `renew_interval` | `600` | How often the open panel renews the cookie, in seconds. |
| `sidebar_title` | `Frigate` | Sidebar title of the panel. |
| `sidebar_icon` | `mdi:cctv` | Sidebar icon of the panel. |
| `panel_path` | `frigate` | URL path of the panel, for example `/frigate`. |

Custom Frigate roles, such as a role limited to some cameras, must exist in Frigate's
`auth.roles`.

## Notes and limitations

- **Session lifetime.** The Frigate username is the Home Assistant login name, and that user
  does not have to exist in Frigate. Because Frigate cannot refresh tokens for unknown users,
  a token works for about `token_ttl - refresh_time` seconds, which is 30 minutes with the
  defaults. The open panel keeps renewing it. After a logout from Home Assistant, or when the
  tab is closed, Frigate access ends within that window.
- **Logout.** Frigate's logout button inside the iframe has no lasting effect: the panel
  issues a new cookie on its next renewal.
- **No trailing slash in `start_path`.** Frigate loads its translations from a relative
  path, so a page such as `/explore/` breaks the UI: it shows raw translation keys, and
  numbers disappear. The integration strips trailing slashes for this reason.
- **Cookie scope.** The cookie is sent to every subdomain of `cookie_domain`.
- **Reverse proxy.** The proxy in front of Home Assistant must pass the `Set-Cookie`
  header through, which most proxies do by default.
- **Security.**
  - Anyone who can read `.jwt_secret` can create Frigate sessions, so keep the file
    readable only by the services that need it.
  - Every Home Assistant administrator becomes a Frigate administrator unless you change
    `admin_role`.
