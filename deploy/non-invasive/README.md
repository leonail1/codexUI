# Non-Invasive Multi-Server Portal

This deployment keeps upstream `codexUI` application code untouched.

You expose multiple backend `codexUI` instances through one public server by adding an outer portal layer:

- a tiny auth service on the public server
- an nginx reverse proxy in front of all backends
- a static server selector page
- one reverse tunnel per backend host

With this setup you get:

- one public HTTPS entrypoint
- one password prompt at login
- server switching without re-entering password
- one active web login globally
- old pages becoming invalid on their next request

What you do **not** get without changing `codexUI` itself:

- the already-open old page will not instantly redraw or auto-redirect on its own
- server switching UI is outside `codexUI`, not embedded in the app

## Layout

- `public-portal/auth_server.py`
  Single-session auth service. No external Python deps.
- `public-portal/index.html`
  Static server selector page.
- `public-portal/nginx.codex-portal.conf.example`
  nginx config template for the public server.
- `public-portal/codex-global-auth.service.example`
  systemd unit for the auth service.
- `public-portal/codex-global-auth.env.example`
  environment file template for the auth service password and cookie names.
- `backends/codexui.service.example`
  systemd user unit for running upstream `codexUI` with `--no-password`.
- `backends/reverse-tunnel.service.example`
  systemd user unit template for the SSH reverse tunnel from backend to public server.

## Runtime model

1. Every backend host runs plain upstream `codexUI` on `127.0.0.1:3100` with `--no-password`.
2. Every backend host creates one reverse tunnel to the public server:
   - `A100 -> 22340`
   - `v100 -> 22339`
   - `node6 -> 22341`
3. The public server routes by the `codex_target` cookie.
4. nginx checks the shared auth cookie through `auth_request`.
5. Logging in somewhere else rotates the single valid session token.
6. The old page keeps rendering until it makes another HTTP request, then it is rejected.

## Backend host setup

Clone your fork with SSH, build locally, then run `codexUI` without backend password:

```bash
git clone git@github.com:leonail1/codexUI.git ~/codexUI
cd ~/codexUI
npm install -g pnpm --prefix "$HOME/.npm-global"
export PATH="$HOME/.npm-global/bin:$PATH"
pnpm install
pnpm run build
systemctl --user daemon-reload
systemctl --user enable --now codexui
systemctl --user enable --now codexui-reverse-tunnel
```

Use the templates in `backends/` and adjust:

- public server username and host
- remote reverse tunnel port
- node binary path if needed

## Public server setup

1. Copy `auth_server.py` to the public server.
2. Create `/etc/codex-global-auth.env` from the example env file.
3. Install the auth service unit.
4. Serve `index.html` from `/var/www/codex-selector/index.html`.
5. Install the nginx config template and replace certificate paths, hostnames, and upstream ports as needed.

## Security notes

- Do not commit the real password into git.
- Keep backend `codexUI` bound to localhost or private interfaces behind the reverse tunnel.
- Use SSH keys for reverse tunnels.
- Keep the auth cookie `HttpOnly` and `Secure`.
