# Homie — cheatsheet

The everyday commands. The repo lives at **`/opt/homie`**. The cockpit is the chat window.

## Open the cockpit (chat with Homie)

```
/opt/homie/scripts/cockpit
```

That works from **any** directory. (The long way is `cd /opt/homie && python3 -m cockpit`.)

If it can't connect, the daemon isn't running:

```
sudo systemctl start homie      # start it
systemctl status homie          # check it's up
```

## Update to the latest

```
cd /opt/homie
sudo git pull --ff-only
sudo systemctl restart homie
```

(Once `HOMIE_SHELL_COMMANDS=1` is live — after one `sudo nixos-rebuild switch` — you can also
just type `/update` in the cockpit and it does all of this for you.)

## Type these in the cockpit chat

| Command | What it does |
|---|---|
| `/help` | list every command |
| `/status` | is Homie up, what it knows, what's playing |
| `/now` | what you're watching right now |
| `/know [word]` | what Homie has learned about your routines (filter by a word) |
| `/recommend` | your picks & taste |
| `/close stremio` | close Stremio (or `/close` for the active window) |
| `/mute [min]` · `/unmute` | quiet the voice for a while |
| `/private on\|off` | stop / allow watching your screen |
| `/model [name]` | list brains or switch (general / dev) |
| `/update` · `/restart` | pull+restart · restart the service |
| `/rebuild` · `/reboot` · `/rollback` | apply OS changes · reboot · undo last update |

> Plain text (no leading `/`) is a question to the brain. The brain only answers when a model is
> served and `HOMIE_LLM_URL` is set (the RTX 3060 node).

## Stremio media keys (what `/close` and the controls send)

| Key | Effect |
|---|---|
| `Space` | play / pause |
| `n` / `p` | next / previous |
| `→` / `←` | seek forward / back |
| `Esc` | stop / exit fullscreen |

Desktop control (`/close`, the media keys) is only live on the desktop node with
`HOMIE_DESKTOP=1` set in `configuration.nix`.
