import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from bluecon import BlueConAPI

from .const import DEVICE_MANUFACTURER, DOMAIN, HASS_BLUECON_VERSION, SIGNAL_CALL_ENDED

_LOGGER = logging.getLogger(__name__)

# The wifi strength and call history are not worth hitting Fermax's API every 30 s.
SCAN_INTERVAL = timedelta(minutes=5)

# Fermax can take a few seconds to add a finished call to its registry.
HISTORY_REFRESH_DELAY_SECONDS = 15

SIGNAL_TERRIBLE = "terrible"
SIGNAL_BAD = "bad"
SIGNAL_WEAK = "weak"
SIGNAL_GOOD = "good"
SIGNAL_EXCELENT = "excelent"
SIGNAL_UNKNOWN = "unknown"

async def async_setup_entry(hass, config, async_add_entities):
    bluecon: BlueConAPI = hass.data[DOMAIN][config.entry_id]

    pairings = await bluecon.getPairings()

    sensors = []

    for pairing in pairings:
        deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)

        sensors.append(
            BlueConWifiStrenghtSensor(
                bluecon,
                pairing.deviceId,
                deviceInfo
            )
        )
        sensors.append(
            BlueConCallHistorySensor(
                bluecon,
                pairing.deviceId,
                deviceInfo
            )
        )

    async_add_entities(sensors)

class BlueConWifiStrenghtSensor(SensorEntity):
    _attr_should_poll = True

    def __init__(self, bluecon, deviceId, deviceInfo):
        self.__bluecon : BlueConAPI = bluecon
        self.deviceId = deviceId
        self._attr_unique_id = f'{self.deviceId}_connection_status'.lower()
        self._attr_options = [SIGNAL_TERRIBLE, SIGNAL_BAD, SIGNAL_WEAK, SIGNAL_GOOD, SIGNAL_EXCELENT, SIGNAL_UNKNOWN]
        self._attr_native_value = getWirelessSignalText(deviceInfo.wirelessSignal)
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'
        self._attr_translation_key = "wifi-state"

    @property
    def device_class(self) -> SensorDeviceClass | None:
        return SensorDeviceClass.ENUM
    
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
        self._attr_native_value = getWirelessSignalText(deviceInfo.wirelessSignal)

class BlueConCallHistorySensor(SensorEntity):
    """Date of the last call, with the recent call history as an attribute."""

    _attr_should_poll = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    def __init__(self, bluecon, deviceId, deviceInfo):
        self.__bluecon : BlueConAPI = bluecon
        self.deviceId = deviceId
        self._attr_unique_id = f'{self.deviceId}_call_history'.lower()
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'
        self._attr_native_value = None
        self._attr_extra_state_attributes = {"history": []}

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CALL_ENDED.format(self.deviceId), self._call_ended_callback)
        )

    async def _call_ended_callback(self) -> None:
        await asyncio.sleep(HISTORY_REFRESH_DELAY_SECONDS)
        self.async_schedule_update_ha_state(True)

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
            callLogs = await self.__bluecon.getCallHistory(self.deviceId)
        except Exception:
            _LOGGER.exception("Failed to fetch the call history for device %s", self.deviceId)
            return

        if not callLogs:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {"history": []}
            return

        lastCall = callLogs[0].getCallDate()
        if lastCall.tzinfo is None:
            lastCall = lastCall.replace(tzinfo = timezone.utc)

        self._attr_native_value = lastCall
        self._attr_extra_state_attributes = {
            "last_call_has_photo": callLogs[0].photoId is not None,
            "history": [
                {"date": callLog.callDate, "has_photo": callLog.photoId is not None}
                for callLog in callLogs
            ]
        }

def getWirelessSignalText(wirelessSignal):
    if wirelessSignal == 0:
        return SIGNAL_TERRIBLE
    elif wirelessSignal == 1:
        return SIGNAL_BAD
    elif wirelessSignal == 2:
        return SIGNAL_WEAK
    elif wirelessSignal == 3:
        return SIGNAL_GOOD
    elif wirelessSignal == 4:
        return SIGNAL_EXCELENT
    else:
        return SIGNAL_UNKNOWN
