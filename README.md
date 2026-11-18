# ovos-network-log

A network log for [OpenVoiceOS](https://openvoiceos.org): every request OVOS
and its skills and plugins make – when, to which host, who asked – so what the
assistant sends out is something you can look at, not just a promise.

It writes the same log [Emkay](https://emkay.ai) keeps in the browser, in the
same format, so [ovos-skill-guardian](https://github.com/emkay-voice/ovos-skill-guardian)
can answer *"what did you send out today?"* and *"what just happened?"* on any
OpenVoiceOS device too.

```
pip install ovos-network-log            # in the same environment as OVOS
pip install ovos-network-log[bus]       # … and send each request on the messagebus
```

Restart OVOS' services, and the log starts.

## What is logged

For each request: when, the host, the method, the status, the size of the
answer, which package asked (from the call stack: `ovos-skill-wikipedia`,
`ovos-tts-plugin-server` … or `ovos` for OVOS itself) and the service in words.
**Never the path, the query or the body**: some services carry what you said
in the address, and the log must not become the thing it is there to show.

```json
{"t": 1794863530091, "host": "stt.openvoiceos.pt", "method": "POST", "status": 200, "bytes": 52, "who": "ovos-stt-plugin-server", "kind": "stt", "service": "speech recognition (OpenVoiceOS server)"}
```

The format: [docs/network-log.md in Emkay](https://github.com/emkay-voice/emkay/blob/main/docs/network-log.md).
Requests to this machine itself (`localhost`, `127.0.0.1` – the messagebus,
for instance) are not "sent out" and are left out. A request that never got an
answer (offline, refused) is logged with status `0`.

## How

The package puts a small `ovos_network_log.pth` file next to the installed
packages. Python reads `.pth` files when it starts – it is how editable
installs and coverage hook in – and this one imports
`ovos_network_log._startup`, which switches the log on **only in OVOS' own
programs** (`ovos-core`, `ovos-audio`, `ovos-dinkum-listener`, `ovos-phal`,
`ovos-gui-service`, `hivemind-…` – anything named `ovos-…`, `mycroft-…`,
`hivemind-…` or `neon-…`). `pip` or your own scripts in the same environment
are left alone.

It wraps Python's `http.client`, which `urllib`, `urllib3` and `requests` –
what nearly all of OpenVoiceOS uses – go through. Requests made with `httpx`
or `aiohttp` are not seen (yet).

## Where it goes

- **The file** `~/.local/state/emkay/network.jsonl`, one JSON object per line
  (`OVOS_NETWORK_LOG_FILE` changes it). Entries older than seven days are
  dropped when a service starts.
- **The messagebus**, as `ovos.network.request` with the entry as its data,
  with the `bus` extra (`ovos-bus-client`). ovos-skill-guardian listens for it.
  That matters with **Docker** ([ovos-docker](https://github.com/OpenVoiceOS/ovos-docker)),
  where each OVOS service is a container with its own file system: install the
  package in each image you want logged (the skills container makes most of
  the requests), and the bus brings the entries to Guardian wherever it runs.
  `OVOS_NETWORK_LOG_BUS=0` turns this off.

## Settings (environment variables)

| | |
|---|---|
| `OVOS_NETWORK_LOG` | `1`: log in this process whatever it is; `0`: never |
| `OVOS_NETWORK_LOG_FILE` | where the log file is |
| `OVOS_NETWORK_LOG_BUS` | `0`: don't send entries on the messagebus |

## License

Apache-2.0
