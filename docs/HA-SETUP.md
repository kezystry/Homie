# Setting up Home Assistant + your bulbs

This wires Homie's hands: **Homie → Home Assistant → IKEA DIRIGERA → Tradfri bulbs.** HA is the
device layer (eyes, ears, hands); Homie is the learning brain above it. Everything here is
**local** — Homie talks only to your HA on the LAN, never the internet.

You do this once. After it, Homie can actually turn your lights on and off, and it learns your
patterns from the same connection (the friction loop).

---

## 1 · Start Home Assistant

The repo ships a ready-to-run container: **[`deploy/homeassistant/`](../deploy/homeassistant/)**.

```
cd deploy/homeassistant
docker compose up -d            # start HA
```

Then open `http://<this-machine-ip>:8123`, wait ~1 minute, and create your account.

Long-term HA belongs on the **always-on mini-PC** (so the lights work even while the GPU brain
sleeps). To get going you can run it on the main PC for now and move it later — see
`deploy/homeassistant/README.md`. (Heads-up: while HA is on the main PC, that PC must be awake
for the lights to respond, and don't add a real door lock there.)

## 2 · Pair the DIRIGERA hub (this discovers every bulb)

1. In HA: **Settings → Devices & Services → Add Integration → "IKEA DIRIGERA".**
   (If it isn't built in yet, add the `ikea_dirigera` HACS integration first.)
2. When prompted, **press the action button on the back of the DIRIGERA hub** to pair.
3. Every Tradfri bulb already added to the hub in the IKEA app now appears in HA as a
   `light.*` entity. Check **Settings → Devices & Services → Entities** and filter for `light.` —
   you should see one per bulb. Give them clear room names in HA if they aren't already
   (e.g. *Kitchen*, *Living Room*) — Homie uses those names.

> Bulbs not showing? Add them to the DIRIGERA hub in the IKEA Home smart app first, then
> reload the integration. Homie can only see what HA sees.

## 3 · Create a long-lived token (so Homie can connect)

In HA: click your **profile (bottom-left) → Security → Long-lived access tokens → Create
token.** Name it `homie`. **Copy it now** — HA shows it only once.

## 4 · Point Homie at HA

On the Homie box, set two environment variables (e.g. in the systemd unit or `/etc/homie.env`):

```
HOMIE_HOME_URL=ws://mini-pc.local:8123/api/websocket
HOMIE_HOME_TOKEN=<the long-lived token you just copied>
```

With both set, `deploy/home.py` swaps the `LoggingHome` stub for the real
`HomeAssistantClient` automatically — no code change.

## 5 · Discover all the bulbs into Homie's act-map (one command)

This reads every `light.*` entity from your live HA and writes the binding from Homie's
semantic names (`light.kitchen`) to HA's entity_ids — so you never hand-type them:

```
cd /opt/homie
python3 scripts/ha_setup.py            # DRY RUN — prints the proposed map, changes nothing
python3 scripts/ha_setup.py --write    # writes deploy/act_map.toml (backs up the old one)
```

Review the dry run first. Rename any actuator on the left if you want a different word
(`light.lounge` instead of `light.living_room`); the right-hand entity_ids must stay exactly
as HA reports them. Add switches/scenes too with `--domains light,switch,scene`.

## 6 · Protect what Homie must never touch

`deploy/act_map.toml` has a `[never_touch]` block. **Anything listed there is refused even if
mapped** (it can still be *read* for the pattern of life, never *driven*). Keep your door lock
and any heater here until you've explicitly decided otherwise:

```toml
[never_touch]
entities = ["lock.front_door", "climate.office_heater"]
```

(Per the security review: don't put a real door lock on the GPU/movie-PC at all — see
`docs/SCOPE.md`.)

## 7 · Restart and check

```
sudo systemctl restart homie
python3 scripts/status.py --text        # confirm the daemon is up
```

Then flip a light **by hand** at the wall/app — Homie should notice (it learns your
corrections), and within a few days the "What Homie knows about you" page starts filling in.
To confirm Homie can *drive* a bulb, ask it in chat or wait for a learned dusk action.

---

### Why this is safe
- **All local.** `ha_setup.py` and the live adapter connect only to your HA on the LAN. No
  bulb data, tokens, or states ever leave your machines.
- **Least privilege.** Homie can only drive entities you mapped; everything else is refused,
  and `[never_touch]` is a hard stop.
- **One canonical form.** Commands Homie sends and the echoes HA returns are compared through
  the same normalizer, so Homie never mistakes its own action for one of yours.
