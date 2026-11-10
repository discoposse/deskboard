# Install on Ubuntu (kiosk)

This path is for a spare mini PC with one monitor. It takes over tty1 with Cage and a fullscreen WebKit window. SSH is left alone.

## Needs

- Ubuntu 24.04 (other recent Ubuntu releases are usually fine)
- A non-root user that owns the checkout
- HDMI (or similar) display attached

## Steps

1. Copy this repo to the machine, for example `~/deskboard`.
2. Copy `config.example.json` to `config.json` and set `timezone`, `mark`, and optional Tailscale bind.
3. Run the installer as root, with the desk user set:

```bash
sudo DESKBOARD_USER="$USER" ./install.sh
```

The script installs Cage, WebKitGTK bindings, writes systemd units, and enables `deskboard` plus `deskboard-kiosk`.

4. The board serves on port `8730` by default. From the machine: `http://127.0.0.1:8730`. From your laptop on the same Tailscale network, use the Tailscale name or address only if you set `bind_tailscale: true`.

## Day to day

- Content changes through the API or `/?config` show on the next poll (about 5 seconds).
- Python changes: `sudo systemctl restart deskboard`
- Frontend or kiosk changes: `sudo systemctl restart deskboard-kiosk`
- Do not reboot just to test a content or CSS change.
- Do not change the OS timezone. Set `timezone` in `config.json` for the clock display only.

## Optional GitHub token

```bash
# drop-in under /etc/systemd/system/deskboard.service.d/token.conf
[Service]
Environment=DESKBOARD_GITHUB_TOKEN=ghp_example
```

Then `sudo systemctl daemon-reload && sudo systemctl restart deskboard`.
