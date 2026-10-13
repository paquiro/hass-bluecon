# HASS-BlueCon

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

Home Assistant custom integration for **Fermax Blue** video door entry systems (Wi-Fi monitors).

This is a maintained fork of [AfonsoFGarcia/hass-bluecon](https://github.com/AfonsoFGarcia/hass-bluecon). The original integration stopped working when the API keys were removed from its library, and Fermax changed how push notifications are delivered. This fork works again with the current backend.

> **Status:** working. Tested on a Fermax **VEO WIFI MONITOR** with Home Assistant 2026.x (Python 3.14) and the Fermax Blue app 4.4.1. Other models may behave differently.

## Features

| Entity | What it does |
| --- | --- |
| `lock` | Opens the door. It shows as unlocked for a configurable number of seconds. |
| `event` (doorbell) | Fires a `ring` event when someone calls. Use it as an automation trigger. |
| `camera` | Shows the photo of the last call. |
| `sensor` (call history) | Date of the last call. The recent calls are in the `history` attribute. |
| `sensor` (wifi) | Wi-Fi signal strength of the monitor. |
| `binary_sensor` | Whether the monitor is connected. |

Photos of every call are also saved to disk, so you keep a history (see [Photo history](#photo-history)).

## Requirements

- Home Assistant **2024.10** or newer.
- A Fermax Blue account with the monitor already paired in the official app.
- **Fermax API client id and secret.** Fermax offers no official API, so these values are not provided here. You have to supply your own.
- For call detection and photos, the Firebase Cloud Messaging settings of the app: Google API key, sender id, app id, project id and package name. They are optional in the form, but **without them there are no `ring` events and no photos**.

## Installation

### HACS

1. In HACS open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/paquiro/hass-bluecon` with the category **Integration**.
3. Install **Fermax Blue** and restart Home Assistant.

### Manual

Copy `custom_components/bluecon` into the `custom_components` folder of your Home Assistant configuration and restart.

## Setup

1. Settings → Devices & services → **Add integration** → *Fermax Blue*.
2. Fill in your Fermax username and password, the API client id and secret, and (optionally) the FCM settings.

The integration installs its Python dependencies on first start. The `bluecon` library is taken from [paquiro/bluecon](https://github.com/paquiro/bluecon), pinned to a specific commit in `manifest.json`.

## Options

Settings → Devices & services → Fermax Blue → **Configure**:

- **Lock state reset timer**: seconds before the lock goes back to *locked* after opening.
- **Maximum stored call photos per device**: how many photos to keep on disk (`0` keeps all).

## Photo history

After every call the integration downloads the call photo from Fermax and saves it as
`/config/www/bluecon/<device id>/<date>_<photo id>.jpg`. On startup it also recovers the photos of past calls that Fermax still holds, so the history is complete from the first run.

To browse them in Home Assistant, expose the folder as a media source in `configuration.yaml`:

```yaml
homeassistant:
  media_dirs:
    local: /media
    bluecon: /config/www/bluecon
```

Then open **Media → My media → bluecon**. Keep the `local` entry: defining `media_dirs` replaces Home Assistant's default folder.

## Services

- `bluecon.simulate_call`: feeds a fake call (or, with `call_ended: true`, a call end) through the normal notification path. It is meant for testing automations without ringing the doorbell. It does not test the delivery of the real push.

## Troubleshooting

Enable logs for the library and the integration:

```yaml
logger:
  default: warning
  logs:
    bluecon: debug
    custom_components.bluecon: debug
```

Useful messages:

- `App token registration (v2) -> HTTP 200`: the monitor's app token was registered with Fermax.
- `FCM push receiver starting to listen`: the push listener is running.
- `Received FCM notification: type='Call' ...` and `Call started on device ...`: a real call reached Home Assistant.
- `Call registry for device ...: N entries, M with photo`: Fermax's call registry was read.

Do **not** enable debug logging for `push_receiver`: it writes the full push payload, including an access token, to the log.

If you update the integration files by hand, remember that Home Assistant does not reinstall a Python package that is already installed. After changing the pinned `bluecon` commit, reinstall it once:

```bash
docker exec -it homeassistant python3 -m pip install --force-reinstall --no-deps "bluecon @ git+https://github.com/paquiro/bluecon.git@<commit>"
```

## Limitations

- Fermax has no endpoint to read the firmware version, so there is no firmware or update entity.
- Live video and two-way audio are not supported.
- Whether a photo exists for a call is decided by Fermax; calls without a photo in its registry cannot be saved.

## Credits

- [AfonsoFGarcia](https://github.com/AfonsoFGarcia): original integration and library.
- [cvc90](https://github.com/cvc90): Spanish translations and other improvements.
- [paquiro](https://github.com/paquiro): push notification fix, ring event, call photo history and Home Assistant compatibility.

## License

MIT License. See [LICENSE](LICENSE).
