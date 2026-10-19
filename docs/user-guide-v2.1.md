# What's new in 2.1 — quick guide

*2.1.0 (in progress): this guide grows with each test build.*

## For whoever runs a Linux server

### Changed `config.toml`? Run `sudo pennywarden apply-config`
After changing `config.toml` — for example adding a folder to `backup_folders` so an Administrator can choose it for
scheduled backups — run:

```
sudo pennywarden apply-config
```

It does only what the change needs, in this order:
1. **Checks the file first, without stopping anything.** If `config.toml` doesn't parse, a backup folder isn't an
   absolute path or is under `/home`, or the host, port, `trusted_proxies` or `secure_cookies` value is wrong, it says
   what is wrong and **changes nothing**. A backup folder that doesn't exist yet is only a warning.
2. **Lets the service write to the backup folders** (the service is sandboxed and may otherwise write only to its data
   folder).
3. **Restarts PennyWarden and waits until it answers.** If it doesn't come back, the previous settings are put back and
   the service is restarted again.
4. **Tells you** which folders the service may write to, what changed, and where to point your tunnel or proxy.

`sudo pennywarden apply-config --dry-run` shows what it would do and changes nothing. Each run is listed in the audit
log as *Server settings applied*. The installer runs the same command on every install and upgrade, so the two always
agree. (Before 2.1.0 you had to run the whole installer again.)

### The installer follows your Bind Address
The installer's last lines tell you where to point your Cloudflare Tunnel or reverse proxy, using the **Bind Address**
(`host` in `config.toml`):
- `127.0.0.1` (the default): `http://127.0.0.1:8765`, as before.
- `0.0.0.0` (the tunnel or proxy runs on **another machine**): the server's network addresses, plus `127.0.0.1` in case
  the tunnel is on the same machine, with a reminder to limit the port with the firewall and to list the tunnel
  machine's address in `trusted_proxies`.
- one specific address: that address. (Before 2.1.0 such an install was reported as failed.)

The installer still never changes your `config.toml`. Details: [Upgrading](upgrade.md#210-after-the-upgrade) and
[Configuration](configuration.md).
