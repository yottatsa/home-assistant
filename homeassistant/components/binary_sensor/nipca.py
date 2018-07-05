"""
Support for displaying collected data over SNMP.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.snmp/
"""
import asyncio
import logging
from datetime import timedelta
import math
import aiohttp
import async_timeout

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
    CONF_HOST, CONF_NAME, CONF_UNIT_OF_MEASUREMENT, STATE_UNKNOWN,
    CONF_USERNAME, CONF_PASSWORD, CONF_AUTHENTICATION,
    HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION, CONF_URL)


_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['nipca']

SCAN_INTERVAL = timedelta(seconds=10)

DEFAULT_NAME = 'NIPCA Camera'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_AUTHENTICATION, default=HTTP_BASIC_AUTHENTICATION):
        vol.In([HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION]),
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_USERNAME): cv.string,
    vol.Required(CONF_URL): cv.url,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
})


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up a NIPCA Camera Sensor."""
    from ..nipca import NipcaCameraDevice
    device = NipcaCameraDevice.from_config_entry(hass, config_entry)
    async_add_entities([NipcaSensor(hass, device)])

from homeassistant.util import Throttle
from datetime import timedelta

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=30)



class NipcaSensor(Entity):
    def __init__(self, hass, device):
        """Initialize the sensor."""
        self.hass = hass
        self.device = device
        device_info = device.motion_device_info
        self._state = None
        self._events = {}

        self._name = device_info[CONF_NAME]
        self._authentication = device_info.get(CONF_AUTHENTICATION)
        self._username = device_info.get(CONF_USERNAME)
        self._password = device_info.get(CONF_PASSWORD)

        self._auth = None
        if self._username and self._password:
            if self._authentication == HTTP_BASIC_AUTHENTICATION:
                self._auth = aiohttp.BasicAuth(
                    self._username, password=self._password
                )

        self.client = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def is_on(self):
        """Return the state of the sensor."""
        return self.device.motion_detection_enabled and self._state

    @property
    def device_state_attributes(self):
        attributes = self.device._attributes.copy()
        attributes.update(self._events)
        return attributes

    @property
    def device_class(self):
        """Return the device class of the binary sensor."""
        return 'motion'

    @property
    def available(self):
        """Return the name of the sensor."""
        return self.device._on

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    @asyncio.coroutine
    def async_update(self):
        yield from self.hass.async_add_job(self.device.update_info)
        if self.device.motion_detection_enabled and not self.client:
            self.client = self._tail()
        if self.client:
            try:
                with async_timeout.timeout(5, loop=self.hass.loop):
                    yield from next(self.client)

            except TypeError:
                pass

            except asyncio.TimeoutError:
                _LOGGER.error("Timeout getting camera image")

            except aiohttp.ClientError as err:
                _LOGGER.error("Error getting new camera image: %s", err)

            except StopIteration:
                self.client = None
                self._state = None
        if not self.device.motion_detection_enabled:
            self.client = None
        return True

    @asyncio.coroutine
    def _tail(self):
        websession = self.hass.helpers.aiohttp_client.async_get_clientsession()
        response = yield from websession.get(
            self.device.notify_stream_url, auth=self._auth
        )
        while True:
            line = yield from response.content.readline()
            line = line.decode().strip()
            if line:
                _LOGGER.error('nipca %s', line)
                if '=' in line:
                    k, v = line.split('=', 1)
                    self._events[k] = v
                    if k == 'md1' and self._state != v:  # TODO: fix
                        self._state = v
                        yield
