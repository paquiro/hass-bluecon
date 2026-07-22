from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import DeviceInfo
from bluecon import BlueConAPI
from homeassistant.config_entries import ConfigEntry

from .const import DEVICE_MANUFACTURER, DOMAIN, HASS_BLUECON_VERSION

STATE_CONNECTED = "Connected"

async def async_setup_entry(hass, entry: ConfigEntry, async_add_entities):
    bluecon: BlueConAPI = hass.data[DOMAIN][entry.entry_id]

    pairings = await bluecon.getPairings()

    sensors = []

    for pairing in pairings:
        deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)

        sensors.append(
            BlueConConnectionStatusBinarySensor(
                bluecon,
                pairing.deviceId,
                deviceInfo
            )
        )

    async_add_entities(sensors)

class BlueConConnectionStatusBinarySensor(BinarySensorEntity):
    _attr_should_poll = True

    def __init__(self, bluecon, deviceId, deviceInfo):
        self.__bluecon : BlueConAPI = bluecon
        self.deviceId = deviceId
        self._attr_unique_id = f'{self.deviceId}_connection_status'.lower()
        self._attr_is_on = deviceInfo is not None and deviceInfo.connectionState == STATE_CONNECTED
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'

    @property
    def device_class(self) -> BinarySensorDeviceClass | None:
        return BinarySensorDeviceClass.CONNECTIVITY

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
        deviceInfo = await self.__bluecon.getDeviceInfo(self.deviceId)
        self._attr_is_on = deviceInfo is not None and deviceInfo.connectionState == STATE_CONNECTED
