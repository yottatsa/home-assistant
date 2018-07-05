"""
Will open a port in your router for Home Assistant and provide statistics.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/upnp/
"""
from ipaddress import ip_address
import logging
import asyncio

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

import voluptuous as vol

from collections import OrderedDict

from homeassistant.const import (
    CONF_NAME, CONF_USERNAME, CONF_PASSWORD, CONF_AUTHENTICATION,
    HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION, CONF_URL)
from homeassistant.components.camera.mjpeg import CONF_MJPEG_URL, CONF_STILL_IMAGE_URL
from homeassistant.const import (EVENT_HOMEASSISTANT_STOP)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import discovery
from homeassistant.util import get_local_ip

CONF_SSDP_DESCRIPTION = 'ssdp_description'
CONF_UDN = 'udn'

DEPENDENCIES = ['api']

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'nipca'
KEY_API = 'nipca_api'

CONFIG_SCHEMA = vol.Schema({DOMAIN: vol.Schema({})}, extra=vol.ALLOW_EXTRA)

from homeassistant import config_entries

async def async_ensure_domain_data(hass):
    """Ensure hass.data is filled properly."""
    hass.data[DOMAIN] = hass.data.get(DOMAIN, {})
    hass.data[DOMAIN]['devices'] = hass.data[DOMAIN].get('devices', {})
    hass.data[DOMAIN]['discovered'] = hass.data[DOMAIN].get('discovered', {})

@config_entries.HANDLERS.register(DOMAIN)
class FlowHandler(config_entries.ConfigFlow):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def _store_discovery_info(self, discovery_info):
        """Add discovery info."""
        udn = discovery_info['udn']
        self.hass.data[DOMAIN]['discovered'][udn] = discovery_info

    @property
    def _discovered_upnp_igds(self):
        """Get all discovered entries."""
        return self.hass.data[DOMAIN]['discovered']

    @property
    def _configured_upnp_igds(self):
        """Get all configured IGDs."""
        return {
            entry.data[CONF_UDN]: {
                'udn': entry.data[CONF_UDN],
            }
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        }

    async def _async_save_entry(self, import_info):
        """Store UPNP/IGD as new entry."""
        await async_ensure_domain_data(self.hass)
        if not import_info:
            return self.async_abort(reason='host_not_found')

        # ensure we know the host
        name = import_info['name']
        discovery_infos = [info
                           for info in self._discovered_upnp_igds.values()
                           if info['friendly_name'] == name]
        if not discovery_infos:
            return self.async_abort(reason='host_not_found')
        discovery_info = discovery_infos[0]

        return self.async_create_entry(
            title=discovery_info['name'],
            data={
                CONF_URL: discovery_info['urlbase'],
                CONF_UDN: discovery_info['udn'],
                CONF_USERNAME: import_info[CONF_USERNAME],
                CONF_PASSWORD: import_info[CONF_PASSWORD],
            },
        )

    async def async_step_discovery(self, discovery_info):
        await async_ensure_domain_data(self.hass)

        if not discovery_info.get('udn') or not discovery_info.get('urlbase'):
            # errors/warnings
            _LOGGER.warn('UPnP device is missing the udn. Provided info: %r',
                          discovery_info)
            return self.async_abort(reason='incomplete_device')

        # store discovered device
        discovery_info['friendly_name'] = discovery_info.get('name')
        self._store_discovery_info(discovery_info)

        # ensure not already discovered/configured
        if discovery_info.get('udn') in self._configured_upnp_igds:
            return self.async_abort(reason='already_configured')

        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        return await self.async_step_auth()

    async def async_step_auth(self, user_input=None):
        await async_ensure_domain_data(self.hass)

        # if user input given, handle it
        user_input = user_input or {}
        if 'name' in user_input:
            if not user_input[CONF_USERNAME] and \
               not user_input[CONF_PASSWORD]:
                return self.async_abort(reason='no_auth')

            # ensure not already configured
            configured_names = [
                entry['friendly_name']
                for udn, entry in self._discovered_upnp_igds.items()
                if udn in self._configured_upnp_igds
            ]
            if user_input['name'] in configured_names:
                return self.async_abort(reason='already_configured')

            return await self._async_save_entry(user_input)

        # let user choose from all discovered, non-configured, UPnP/IGDs
        names = [
            entry['friendly_name']
            for udn, entry in self._discovered_upnp_igds.items()
            if udn not in self._configured_upnp_igds
        ]
        if not names:
            return self.async_abort(reason='no_devices_discovered')

        return self.async_show_form(
            step_id='auth',
            data_schema=vol.Schema(
                OrderedDict([
                    (vol.Required('name'), vol.In(names)),
                    (vol.Required(CONF_USERNAME), str),
                    (vol.Required(CONF_PASSWORD), str),
                ])
            ))

    async def async_step_import(self, import_info):
        """Import a new UPnP/IGD as a config entry."""
        await async_ensure_domain_data(self.hass)
        return await self._async_save_entry(import_info)


async def async_setup(hass, config):
    """Register a port mapping for Home Assistant via UPnP."""
    await async_ensure_domain_data(hass)
    #await hass.config_entries.flow.async_init(
    #        DOMAIN, context={'source': config_entries.SOURCE_IMPORT}, data=[])
    return True


async def async_setup_entry(hass, entry):
    await async_ensure_domain_data(hass)
    device = NipcaCameraDevice.from_config_entry(hass, entry)
    if not device._on:
        _LOGGER.warn('device is not available')
        return False

    dev_reg = await hass.helpers.device_registry.async_get_registry()
    dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        connections=set(),
        identifiers={
            (DOMAIN, entry.data[CONF_URL])
        },
        manufacturer=device._attributes.get('brand'),
        name=device._attributes.get('name'),
        # They just have 1 gateway model. Type is not exposed yet.
        model=device._attributes.get('model'),
        sw_version=device._attributes.get('version'),
    )

    hass.async_create_task(hass.config_entries.async_forward_entry_setup(
        entry, 'camera'
    ))
    hass.async_create_task(hass.config_entries.async_forward_entry_setup(
        entry, 'binary_sensor'
    ))
    return True


class NipcaCameraDevice(object):
    """Get the latest sensor data."""
    COMMON_INFO = '{}/common/info.cgi'
    STREAM_INFO = '{}/config/stream_info.cgi'
    MOTION_INFO = '{}/motion.cgi'  # D-Link has only this one working
    STILL_IMAGE = '{}/image/jpeg.cgi'
    NOTIFY_STREAM = '{}/config/notify_stream.cgi'

    @classmethod
    def from_config_entry(cls, hass, config_entry):
        conf = config_entry.data
        url = conf[CONF_URL]
        data = hass.data.setdefault(KEY_API, {})
        if config_entry.entry_id in data:
            device = data[config_entry.entry_id]
        else:
            device = cls(hass, conf, url)
            device.update_info()
            data[config_entry.entry_id] = device
        return device

    def __init__(self, hass, conf, url):
        self.hass = hass
        self.conf = conf
        self.url = url

        self._authentication = self.conf.setdefault(CONF_AUTHENTICATION, HTTP_BASIC_AUTHENTICATION)
        self._username = self.conf.get(CONF_USERNAME)
        self._password = self.conf.get(CONF_PASSWORD)
        if self._username and self._password:
            if self._authentication == HTTP_DIGEST_AUTHENTICATION:
                self._auth = HTTPDigestAuth(self._username, self._password)
            else:
                self._auth = HTTPBasicAuth(self._username, self._password)
        else:
            self._auth = None

        self._attributes = {}
        self._on = False

    @property
    def name(self):
        return self._attributes['name']

    @property
    def mjpeg_url(self):
        return self.url + self._attributes['vprofileurl1']

    @property
    def still_image_url(self):
        return self._build_url(self.STILL_IMAGE)

    @property
    def notify_stream_url(self):
        return self._build_url(self.NOTIFY_STREAM)

    @property
    def motion_detection_enabled(self):
        """Return the camera motion detection status."""
        return self._attributes.get('motiondetectionenable') == '1'

    @property
    def camera_device_info(self):
        device_info = self.conf.copy()
        device_info.update(
            {
                'platform': DOMAIN,
                'url': self.url,
                CONF_NAME: self.name,
                CONF_MJPEG_URL: self.mjpeg_url,
                CONF_STILL_IMAGE_URL: self.still_image_url,
            }
        )
        return device_info

    @property
    def motion_device_info(self):
        device_info = self.conf.copy()
        device_info.update(
            {
                'platform': DOMAIN,
                'url': self.url,
                CONF_NAME: '{} motion sensor'.format(self.name),
            }
        )
        return device_info

    def update_info(self):
        self._on = True
        self._attributes.update(self._nipca(self.COMMON_INFO))
        self._attributes.update(self._nipca(self.STREAM_INFO))
        self._attributes.update(self._nipca(self.MOTION_INFO))

    def _nipca(self, suffix):
        """Return a still image response from the camera."""
        if not self._on:
            return {}
        url = self._build_url(suffix)
        try:
            if self._auth:
                req = requests.get(url, auth=self._auth, timeout=10)
            else:
                req = requests.get(url, timeout=10)
        except (requests.exceptions.ConnectTimeout, OSError):
            self._on = False
            return {}

        result = {}
        for l in req.iter_lines():
            k, v = l.decode().strip().split('=', 1)
            result[k.lower()] = v
        return result

    def _build_url(self, suffix):
        return suffix.format(self.url)
