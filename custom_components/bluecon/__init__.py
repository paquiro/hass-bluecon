import json
import logging
import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from .const import CONF_LOCK_STATE_RESET, CONF_MAX_STORED_PHOTOS, DEFAULT_MAX_STORED_PHOTOS, DOMAIN, SIGNAL_CALL_ENDED, SIGNAL_CALL_STARTED
from .ConfigFolderOAuthTokenStorage import ConfigFolderOAuthTokenStorage
from .ConfigFolderNotificationInfoStorage import ConfigFolderNotificationInfoStorage
from .config_flow import BlueConConfigFlow
from homeassistant.const import (
    CONF_API_KEY,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    EVENT_HOMEASSISTANT_STOP,
    Platform
)
from homeassistant.helpers.dispatcher import dispatcher_send
from bluecon import BlueConAPI, INotification, CallNotification, CallEndNotification, IOAuthTokenStorage, INotificationInfoStorage, OAuthToken
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from custom_components.bluecon.const import CONF_PACKAGE_NAME, CONF_APP_ID, CONF_PROJECT_ID, CONF_SENDER_ID

_LOGGER = logging.getLogger(__name__)



PLATFORMS: list[str] = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.LOCK, Platform.CAMERA, Platform.SENSOR]

SERVICE_SIMULATE_CALL = "simulate_call"
SIMULATE_CALL_SCHEMA = vol.Schema({vol.Optional("call_ended", default = False): cv.boolean})

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    def notification_callback(notification: INotification):
        if type(notification) is CallNotification:
            _LOGGER.info("Call started on device %s, door key %r", notification.deviceId, notification.accessDoorKey)
            dispatcher_send(hass, SIGNAL_CALL_STARTED.format(notification.deviceId, notification.accessDoorKey))
        elif type(notification) is CallEndNotification:
            _LOGGER.info("Call ended on device %s", notification.deviceId)
            dispatcher_send(hass, SIGNAL_CALL_ENDED.format(notification.deviceId))
        else:
            _LOGGER.info("Ignoring notification of type %s", type(notification).__name__)

    hass.data[DOMAIN] = {
        "bluecon": None
    }

    bluecon = await BlueConAPI.create_already_authed(
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data.get(CONF_SENDER_ID, None),
        entry.data.get(CONF_API_KEY, None),
        entry.data.get(CONF_PROJECT_ID, None),
        entry.data.get(CONF_APP_ID, None),
        entry.data.get(CONF_PACKAGE_NAME, None),
        notification_callback, 
        ConfigFolderOAuthTokenStorage(hass), 
        ConfigFolderNotificationInfoStorage(hass)
    )

    if entry.data.get(CONF_SENDER_ID, None) is not None and entry.data.get(CONF_API_KEY, None) is not None and entry.data.get(CONF_PROJECT_ID, None) is not None and entry.data.get(CONF_APP_ID, None) is not None and entry.data.get(CONF_PACKAGE_NAME, None) is not None:
        await bluecon.startNotificationListener(hass)

        @callback
        async def cleanup(event):
            await bluecon.stopNotificationListener()
        
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cleanup)

    hass.data[DOMAIN][entry.entry_id] = bluecon

    async def simulate_call(call: ServiceCall) -> None:
        """Test helper: feeds a fake call (or call end) through the real notification path.

        It exercises everything after the push has been received (event entity,
        camera refresh and photo saving), but not the push delivery itself."""
        callEnded = call.data["call_ended"]
        for pairing in await bluecon.getPairings():
            if callEnded:
                notification_callback(CallEndNotification({
                    "DeviceId": pairing.deviceId,
                    "NotificationTitle": "Simulated call end",
                    "NotificationBody": "Simulated call end",
                    "CallAs": ""
                }))
            else:
                for doorKey in pairing.accessDoorMap:
                    notification_callback(CallNotification({
                        "DeviceId": pairing.deviceId,
                        "FermaxToken": "simulated",
                        "SocketUrl": "",
                        "NotificationTitle": "Simulated call",
                        "NotificationBody": "Simulated call",
                        "CallAs": "",
                        "RoomId": "",
                        "SendAcknowledge": False,
                        "AccessDoorKey": doorKey
                    }, "simulated"))

    hass.services.async_register(DOMAIN, SERVICE_SIMULATE_CALL, simulate_call, schema = SIMULATE_CALL_SCHEMA)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.services.async_remove(DOMAIN, SERVICE_SIMULATE_CALL)

    return unload_ok

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    tempNotificationInfoStorage: INotificationInfoStorage = ConfigFolderNotificationInfoStorage(hass)
    tempOAuthTokenStorage: IOAuthTokenStorage = ConfigFolderOAuthTokenStorage(hass)

    if config_entry.version == 1:
        try:
            with open("credentials.json", "r") as f:
                credentials = json.load(f)
        except FileNotFoundError:
            credentials = None
        
        try:
            with open("persistent_ids.txt", "r") as f:
                persistentIds = [x.strip() for x in f]
        except FileNotFoundError:
            persistentIds = None
        
        await tempOAuthTokenStorage.storeOAuthToken(OAuthToken.fromJson(config_entry.data["token"]))
        await tempNotificationInfoStorage.storeCredentials(credentials)
        for persistentId in persistentIds:
            await tempNotificationInfoStorage.storePersistentId(persistentId)

    if config_entry.version == 2:

        await tempOAuthTokenStorage.storeOAuthToken(OAuthToken.fromJson(config_entry.data["token"]))
        await tempNotificationInfoStorage.storeCredentials(config_entry.data["credentials"])
        for persistentId in config_entry.data["persistentIds"]:
            await tempNotificationInfoStorage.storePersistentId(persistentId)

    if config_entry.version == 3:
        await tempOAuthTokenStorage.storeOAuthToken(OAuthToken.fromJson(config_entry.options["token"]))
        await tempNotificationInfoStorage.storeCredentials(config_entry.options["credentials"])
        for persistentId in config_entry.options["persistentIds"]:
            await tempNotificationInfoStorage.storePersistentId(persistentId)

    if config_entry.version < 6:
        config_entry.version = BlueConConfigFlow.VERSION
        hass.config_entries.async_update_entry(config_entry, data = {
                        CONF_CLIENT_ID: "",
                        CONF_CLIENT_SECRET: ""
                    }, options = { CONF_LOCK_STATE_RESET: 5, CONF_MAX_STORED_PHOTOS: DEFAULT_MAX_STORED_PHOTOS })
    
    return True
