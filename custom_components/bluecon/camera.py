import logging
from datetime import datetime
from pathlib import Path

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CONF_API_KEY
from homeassistant.config_entries import ConfigEntry


from bluecon import BlueConAPI

from .const import (
    CONF_MAX_STORED_PHOTOS,
    DEFAULT_MAX_STORED_PHOTOS,
    DEVICE_MANUFACTURER,
    DOMAIN,
    HASS_BLUECON_VERSION,
    PHOTO_STORAGE_SUBDIR,
    SIGNAL_CALL_ENDED,
    CONF_PACKAGE_NAME,
    CONF_APP_ID,
    CONF_PROJECT_ID,
    CONF_SENDER_ID,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    cameras = []

    if entry.data.get(CONF_SENDER_ID, None) is not None and entry.data.get(CONF_API_KEY, None) is not None and entry.data.get(CONF_PROJECT_ID, None) is not None and entry.data.get(CONF_APP_ID, None) is not None and entry.data.get(CONF_PACKAGE_NAME, None) is not None:
        bluecon : BlueConAPI = hass.data[DOMAIN][entry.entry_id]
        maxStoredPhotos = entry.options.get(CONF_MAX_STORED_PHOTOS, DEFAULT_MAX_STORED_PHOTOS)

        pairings = await bluecon.getPairings()

        for pairing in pairings:
            deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)
            if deviceInfo.photoCaller:
                image = await bluecon.getLastPicture(pairing.deviceId)
                photosDir = Path(hass.config.path("www", PHOTO_STORAGE_SUBDIR, pairing.deviceId))
                cameras.append(
                    BlueConStillCamera(
                        bluecon,
                        pairing.deviceId,
                        image,
                        deviceInfo,
                        photosDir,
                        maxStoredPhotos
                    )
                )

    async_add_entities(cameras)

def _save_photo_to_disk(photosDir: Path, image: bytes, maxStoredPhotos: int) -> None:
    """Write a call photo to disk and prune old ones. Runs in the executor."""
    photosDir.mkdir(parents = True, exist_ok = True)
    photoPath = photosDir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}.jpg"
    photoPath.write_bytes(image)

    if maxStoredPhotos > 0:
        storedPhotos = sorted(photosDir.glob("*.jpg"))
        for stalePhoto in storedPhotos[:-maxStoredPhotos]:
            stalePhoto.unlink(missing_ok = True)

class BlueConStillCamera(Camera):
    _attr_should_poll = False

    def __init__(self, bluecon: BlueConAPI, deviceId, image: bytes | None, deviceInfo, photosDir: Path, maxStoredPhotos: int):
        super().__init__()
        self.bluecon = bluecon
        self.deviceId = deviceId
        self._attr_unique_id = f'{self.deviceId}_last_still'.lower()
        self.__image: bytes | None = image
        self.__model = f'{deviceInfo.type} {deviceInfo.subType} {deviceInfo.family}'
        self.__photosDir = photosDir
        self.__maxStoredPhotos = maxStoredPhotos

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CALL_ENDED.format(self.deviceId), self._call_ended_callback)
        )

    async def _call_ended_callback(self) -> None:
        image = await self.bluecon.getLastPicture(self.deviceId)
        if image is not None:
            self.__image = image
            try:
                await self.hass.async_add_executor_job(
                    _save_photo_to_disk, self.__photosDir, image, self.__maxStoredPhotos
                )
            except OSError:
                _LOGGER.exception("Failed to save call photo for device %s", self.deviceId)
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
    
    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        return self.__image
