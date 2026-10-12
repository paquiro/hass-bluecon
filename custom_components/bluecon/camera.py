import asyncio
import logging
import re
from datetime import timezone
from pathlib import Path

from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CONF_API_KEY
from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util


from bluecon import BlueConAPI

from .const import (
    CONF_MAX_STORED_PHOTOS,
    DEFAULT_MAX_STORED_PHOTOS,
    DEVICE_MANUFACTURER,
    DOMAIN,
    PHOTO_STORAGE_SUBDIR,
    SIGNAL_CALL_ENDED,
    CONF_PACKAGE_NAME,
    CONF_APP_ID,
    CONF_PROJECT_ID,
    CONF_SENDER_ID,
)

_LOGGER = logging.getLogger(__name__)

PHOTO_FETCH_ATTEMPTS = 4
PHOTO_FETCH_DELAY_SECONDS = 8

# How many registry entries to look at when the retention limit is "keep everything".
PHOTO_HISTORY_LOOKBACK_WHEN_UNLIMITED = 50

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    cameras = []

    if entry.data.get(CONF_SENDER_ID, None) is not None and entry.data.get(CONF_API_KEY, None) is not None and entry.data.get(CONF_PROJECT_ID, None) is not None and entry.data.get(CONF_APP_ID, None) is not None and entry.data.get(CONF_PACKAGE_NAME, None) is not None:
        bluecon : BlueConAPI = hass.data[DOMAIN][entry.entry_id]
        maxStoredPhotos = entry.options.get(CONF_MAX_STORED_PHOTOS, DEFAULT_MAX_STORED_PHOTOS)

        pairings = await bluecon.getPairings()

        for pairing in pairings:
            deviceInfo = await bluecon.getDeviceInfo(pairing.deviceId)
            if not deviceInfo.photoCaller:
                _LOGGER.info("Device %s does not take call photos (photoCaller is off), no camera created", pairing.deviceId)
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

def _safePhotoId(photoId: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-]", "", photoId)

def _storedPhotoIds(photosDir: Path) -> set[str]:
    """Ids of the photos already on disk. Files are named <date>_<photoId>.jpg. Runs in the executor."""
    if not photosDir.exists():
        return set()
    return {path.stem.split("_", 1)[1] for path in photosDir.glob("*.jpg") if "_" in path.stem}

def _savePhotoToDisk(photosDir: Path, image: bytes, fileStem: str) -> None:
    """Write a call photo to disk. Runs in the executor."""
    photosDir.mkdir(parents = True, exist_ok = True)
    (photosDir / f"{fileStem}.jpg").write_bytes(image)

def _prunePhotos(photosDir: Path, maxStoredPhotos: int) -> None:
    """Keep only the newest photos (names start with the call date). Runs in the executor."""
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
        self.__syncLock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CALL_ENDED.format(self.deviceId), self._call_ended_callback)
        )
        # Fermax keeps the photos of past calls, so recover the ones that are not on disk yet.
        self.hass.async_create_background_task(self._backfill(), f"bluecon photo backfill {self.deviceId}")

    async def _backfill(self) -> None:
        try:
            saved = await self._syncPhotos()
            _LOGGER.info("Photo history for device %s: %s photo(s) recovered from Fermax", self.deviceId, saved)
        except Exception:
            _LOGGER.exception("Failed to recover the photo history for device %s", self.deviceId)

    async def _syncPhotos(self) -> int:
        """Save every photo in Fermax's call registry that is not on disk yet. Returns how many were saved."""
        async with self.__syncLock:
            lookback = self.__maxStoredPhotos if self.__maxStoredPhotos > 0 else PHOTO_HISTORY_LOOKBACK_WHEN_UNLIMITED
            callLogs = await self.bluecon.getCallHistory(self.deviceId, lookback)
            withPhoto = [callLog for callLog in callLogs if callLog.photoId]
            if not withPhoto:
                return 0

            storedIds = await self.hass.async_add_executor_job(_storedPhotoIds, self.__photosDir)
            missing = [callLog for callLog in withPhoto if _safePhotoId(callLog.photoId) not in storedIds]

            newest = withPhoto[0]  # getCallHistory returns the newest first
            fetched: dict[str, bytes] = {}
            saved = 0
            for callLog in reversed(missing):  # oldest first
                image = await self.bluecon.getCallPhoto(callLog.photoId)
                if image is None:
                    continue
                callDate = callLog.getCallDate()
                if callDate.tzinfo is None:
                    callDate = callDate.replace(tzinfo = timezone.utc)
                fileStem = f"{dt_util.as_local(callDate):%Y%m%dT%H%M%S}_{_safePhotoId(callLog.photoId)}"
                try:
                    await self.hass.async_add_executor_job(_savePhotoToDisk, self.__photosDir, image, fileStem)
                except OSError:
                    _LOGGER.exception("Failed to save call photo for device %s", self.deviceId)
                    continue
                fetched[callLog.photoId] = image
                saved += 1

            if saved:
                await self.hass.async_add_executor_job(_prunePhotos, self.__photosDir, self.__maxStoredPhotos)
                _LOGGER.info("Saved %s call photo(s) for device %s in %s", saved, self.deviceId, self.__photosDir)

            if newest.photoId in fetched:
                self.__image = fetched[newest.photoId]
                self.async_write_ha_state()
            return saved

    async def _call_ended_callback(self) -> None:
        # Fermax can take a few seconds to add the photo of a call to its registry.
        for attempt in range(1, PHOTO_FETCH_ATTEMPTS + 1):
            try:
                if await self._syncPhotos() > 0:
                    return
            except Exception:
                _LOGGER.exception("Failed to fetch the call photo for device %s", self.deviceId)

            _LOGGER.info("No new call photo yet for device %s (attempt %s/%s)", self.deviceId, attempt, PHOTO_FETCH_ATTEMPTS)
            if attempt < PHOTO_FETCH_ATTEMPTS:
                await asyncio.sleep(PHOTO_FETCH_DELAY_SECONDS)

        _LOGGER.info("Fermax has no new photo for the last call on device %s, nothing saved", self.deviceId)

    @property
    def device_info(self) -> DeviceInfo | None:
        return DeviceInfo(
            identifiers = {
                (DOMAIN, self.deviceId)
            },
            name = f'{self.__model} {self.deviceId}',
            manufacturer = DEVICE_MANUFACTURER,
            model = self.__model
        )

    def camera_image(self, width: int | None = None, height: int | None = None) -> bytes | None:
        return self.__image
