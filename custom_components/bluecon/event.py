from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from bluecon import BlueConAPI
from homeassistant.const import CONF_API_KEY
from homeassistant.config_entries import ConfigEntry

from .const import DEVICE_MANUFACTURER, DOMAIN, HASS_BLUECON_VERSION, SIGNAL_CALL_STARTED, CONF_PACKAGE_NAME, CONF_APP_ID, CONF_PROJECT_ID, CONF_SENDER_ID

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    events = []

    if entry.data.get(CONF_SENDER_ID, None) is not None and entry.data.get(CONF_API_KEY, None) is not None and entry.data.get(CONF_PROJECT_ID, None) is not None and entry.data.get(CONF_APP_ID, None) is not None and entry.data.get(CONF_PACKAGE_NAME, None) is not None:
        bluecon: BlueConAPI = hass.data[DOMAIN][entry.entry_id]

        pairings = await bluecon.getPairings()

        for pairing in pairings:
            deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)
            for accessDoorName in pairing.accessDoorMap:
                events.append(
                    BlueConCallEvent(
                        pairing.deviceId,
                        accessDoorName,
                        deviceInfo
                    )
                )

    async_add_entities(events)

class BlueConCallEvent(EventEntity):
    _attr_should_poll = False
    _attr_device_class = EventDeviceClass.DOORBELL
    _attr_event_types = ["ring"]

    def __init__(self, deviceId, accessDoorName, deviceInfo):
        self.lockId = f'{deviceId}_{accessDoorName}'
        self.deviceId = deviceId
        self.accessDoorName = accessDoorName
        self._attr_unique_id = f'{self.lockId}_ring'.lower()
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CALL_STARTED.format(self.deviceId, self.accessDoorName), self._call_started_callback)
        )

    @callback
    def _call_started_callback(self) -> None:
        self._trigger_event("ring")
        self.async_write_ha_state()

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
