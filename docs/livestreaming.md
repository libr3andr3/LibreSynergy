# Livestreaming (OwnCast) — profile: `stream`

Self-hosted livestreams with live chat on the watch page: OBS pushes RTMP to
your node, OwnCast transcodes to HLS, viewers watch at `https://live.<domain>`.
No YouTube/Twitch in the loop — the stream never leaves infrastructure you own.

```
OBS ── rtmp://live.<domain>:1935 ──► VPS relay (raw-TCP forward, never decrypts)
                                        │ WireGuard
                                        ▼
                               node: OwnCast :1935 ── HLS ──► Caddy ──► viewers
                                        (web UI + chat on 127.0.0.1:8600)
```

## Enable

```bash
./bin/ls up stream                    # start OwnCast
./bin/ls route web live 8600          # https://live.<domain> (player + chat)
./bin/ls route tcp rtmp 1935          # raw RTMP ingest for OBS
```

Create the DNS A record the route commands print (`live.<domain>` → relay IP).

## Harden before you announce (required)

OwnCast ships with admin login `admin` / `abc123` and a default stream key.
Replace both via the admin API and keep the values in
`${LS_SECRETS_DIR}/owncast.env`:

```bash
AP=$(openssl rand -hex 16); SK=$(openssl rand -hex 16)
b(){ curl -s -u "admin:$1" -X POST -H 'Content-Type: application/json' \
       -d "$2" "http://127.0.0.1:8600/api/admin/config/$3"; }
b abc123 "{\"value\":\"$AP\"}" adminpass
b "$AP"  "{\"value\":[{\"key\":\"$SK\",\"comment\":\"OBS\"}]}" streamkeys
b "$AP"  "{\"value\":\"My Community Live\"}" name
b "$AP"  "{\"value\":\"https://live.<domain>\"}" serverurl
umask 077
printf 'OWNCAST_ADMIN_USER=admin\nOWNCAST_ADMIN_PASSWORD=%s\nOWNCAST_STREAM_KEY=%s\n' \
  "$AP" "$SK" > secrets/owncast.env
```

(Run on the node; the admin API listens only on loopback.)

## Stream from OBS

- Settings → Stream → Service: **Custom**
- Server: `rtmp://live.<domain>:1935/live`
- Stream key: the `OWNCAST_STREAM_KEY` value

Go live in OBS; the watch page picks the stream up within a few seconds.
Viewers chat directly on the watch page (chat can be toggled or moderated from
`https://live.<domain>/admin`). For persistent community discussion around a
stream, link the Matrix room — OwnCast chat is ephemeral to the broadcast.

## Notes

- Output quality/variants (and hardware transcoding) are configured in the
  admin UI under Video; the default single 720p variant is CPU-light.
- Recordings: OwnCast does not archive by default. Record locally in OBS, or
  enable S3-compatible storage in the admin UI if you want server-side copies.
- The `live.` vhost sends a `frame-ancestors` CSP that allows embedding the
  player on your landing and app pages (`<iframe src="https://live.<domain>/embed/video">`).
