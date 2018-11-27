"""
Support for IP Cameras.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/camera.mjpeg/
"""
import asyncio
import logging
from contextlib import closing

import aiohttp
import async_timeout
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth
import voluptuous as vol

from homeassistant.const import (
    CONF_NAME, CONF_USERNAME, CONF_PASSWORD, CONF_AUTHENTICATION,
    HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION, CONF_URL)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.aiohttp_client import (
    async_get_clientsession, async_aiohttp_proxy_web)
from homeassistant.helpers import config_validation as cv

from homeassistant.components.camera.mjpeg import MjpegCamera, CONF_MJPEG_URL, CONF_STILL_IMAGE_URL, PLATFORM_SCHEMA

_LOGGER = logging.getLogger(__name__)

DEPENDENCIES = ['nipca']

CONTENT_TYPE_HEADER = 'Content-Type'

DEFAULT_NAME = 'NIPCA Camera'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_URL): cv.url,
})


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up a NIPCA Camera."""
    from ..nipca import NipcaCameraDevice
    device = NipcaCameraDevice.from_config_entry(hass, config_entry)
    async_add_entities([NipcaCamera(hass, device)])


class NipcaCamera(MjpegCamera):
    """
    An implementation of an IP camera that is reachable over a URL.
    http://gurau-audibert.hd.free.fr/josdblog/wp-content/uploads/2013/09/CGI_2121.pdf
    """

    def __init__(self, hass, device):
        """Initialize a MJPEG camera from NIPCA."""
        self.device = device
        super().__init__(self.device.camera_device_info)

    @property
    def brand(self):
        """Return the camera brand."""
        return self.device._attributes['brand']

    @property
    def model(self):
        """Return the camera model."""
        return self.device._attributes['model']

    @property
    def motion_detection_enabled(self):
        """Return the camera motion detection status."""
        return self.device.motion_detection_enabled
