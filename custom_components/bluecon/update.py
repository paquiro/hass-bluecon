import logging
from datetime import timedelta

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from bluecon import BlueConAPI

from .const import DEVICE_MANUFACTURER, DOMAIN, HASS_BLUECON_VERSION

_LOGGER = logging.getLogger(__name__)

# Firmware changes rarely, there is no point in asking more often.
SCAN_INTERVAL = timedelta(hours = 6)

# The response of Fermax's firmware endpoint has not been confirmed against a real device,
# so the version fields are looked up under every plausible name.
INSTALLED_VERSION_KEYS = ("currentVersion", "installedVersion", "currentFirmwareVersion", "firmwareVersion", "version")
LATEST_VERSION_KEYS = ("availableVersion", "latestVersion", "newFirmwareVersion", "targetVersion")

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    bluecon: BlueConAPI = hass.data[DOMAIN][entry.entry_id]

    pairings = await bluecon.getPairings()

    updates = []

    for pairing in pairings:
        deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)
        updates.append(
            BlueConFirmwareUpdate(
                bluecon,
                pairing.deviceId,
                deviceInfo
            )
        )

    async_add_entities(updates)

def _firstValue(payload: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return None

class BlueConFirmwareUpdate(UpdateEntity):
    _attr_should_poll = True

    def __init__(self, bluecon: BlueConAPI, deviceId, deviceInfo):
        self.__bluecon : BlueConAPI = bluecon
        self.deviceId = deviceId
        self._attr_unique_id = f'{self.deviceId}_firmware'.lower()
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'
        self._attr_title = "Fermax firmware"

    @property
    def device_info(self) -> DeviceInfo | None:
        return DeviceInfo(
            identifiers = {
                (DOMAIN, self.deviceId)
            },
            name = f'{self.__model} {self.deviceId}',
            manufacturer = DEVICE_MANUFACTURER,
            model = self.__model,
            sw_version = HASS_BLUECON_VERSION
        )

    async def async_update(self):
        try:
            status = await self.__bluecon.getFirmwareUpdateStatus(self.deviceId)
        except Exception:
            _LOGGER.exception("Failed to fetch the firmware status for device %s", self.deviceId)
            return

        if not isinstance(status, dict):
            _LOGGER.info("Fermax returned no usable firmware status for device %s: %r", self.deviceId, status)
            return

        # Kept visible so the real shape of the response can be inspected from the UI.
        self._attr_extra_state_attributes = {"raw": status}

        installed = _firstValue(status, INSTALLED_VERSION_KEYS)
        latest = _firstValue(status, LATEST_VERSION_KEYS) or installed

        if installed is None:
            _LOGGER.info("Could not find a firmware version in the response for device %s, keys: %s", self.deviceId, sorted(status.keys()))

        self._attr_installed_version = installed
        self._attr_latest_version = latest
