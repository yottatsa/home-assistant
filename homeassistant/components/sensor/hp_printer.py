"""
Support for displaying collected data over SNMP.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.snmp/
"""
import logging
from datetime import timedelta
import math

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.helpers.entity import Entity
from homeassistant.const import (
    CONF_HOST, CONF_NAME, CONF_UNIT_OF_MEASUREMENT, STATE_UNKNOWN,
    CONF_VALUE_TEMPLATE)
from homeassistant.util import Throttle

REQUIREMENTS = ['pysnmp==4.4.5']

_LOGGER = logging.getLogger(__name__)

CONF_BASEOID = 'baseoid'
CONF_COMMUNITY = 'community'
CONF_VERSION = 'snmp_version'
CONF_PORT = 'snmp_port'
CONF_ACCEPT_ERRORS = 'accept_errors'
CONF_DEFAULT_VALUE = 'default_value'

DEFAULT_COMMUNITY = 'public'
DEFAULT_HOST = 'localhost'
DEFAULT_NAME = 'SNMP'
DEFAULT_PORT = '161'
DEFAULT_VERSION = '1'

SNMP_VERSIONS = {
    '1': 0,
    '2c': 1
}

ERRORS = {
    7: 'Low paper',
    6: 'No paper',
    5: 'Low toner',
    4: 'No toner',
    3: 'Door open',
    2: 'Jammed',
    1: 'Offline',
    0: 'Service Requested',
    # inputTrayMissing      8
    # outputTrayMissing     9
    # markerSupplyMissing  10
    # outputNearFull       11
    # outputFull           12
    # inputTrayEmpty       13
    # overduePreventMaint  14
}

STATUS = {
    1: 'Other',
    3: 'Idle',
    4: 'Printing',
}

MIN_TIME_BETWEEN_UPDATES = timedelta(seconds=15)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_BASEOID): cv.string,
    vol.Optional(CONF_ACCEPT_ERRORS, default=False): cv.boolean,
    vol.Optional(CONF_COMMUNITY, default=DEFAULT_COMMUNITY): cv.string,
    vol.Optional(CONF_DEFAULT_VALUE): cv.string,
    vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
    vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
    vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
    vol.Optional(CONF_VERSION, default=DEFAULT_VERSION): vol.In(SNMP_VERSIONS),
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the SNMP sensor."""
    from pysnmp.hlapi import (
        getCmd, CommunityData, SnmpEngine, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity)

    config = config.copy()
    config.update(discovery_info)
    properties = discovery_info.get('properties', {})

    name = config.get(CONF_NAME) or properties.get('ty')
    host = config.get(CONF_HOST)
    port = DEFAULT_PORT # config.get(CONF_PORT)
    community = DEFAULT_COMMUNITY # config.get(CONF_COMMUNITY)
    baseoid = '1.3.6.1.2.1.25' # config.get(CONF_BASEOID)
    unit = config.get(CONF_UNIT_OF_MEASUREMENT)
    version = DEFAULT_VERSION #config.get(CONF_VERSION)
    accept_errors = config.get(CONF_ACCEPT_ERRORS)
    default_value = config.get(CONF_DEFAULT_VALUE)
    value_template = config.get(CONF_VALUE_TEMPLATE)

    if value_template is not None:
        value_template.hass = hass

    errindication, _, _, _ = next(
        getCmd(SnmpEngine(),
               CommunityData(community, mpModel=SNMP_VERSIONS[version]),
               UdpTransportTarget((host, port)),
               ContextData(),
               ObjectType(ObjectIdentity(baseoid))))

    if errindication and not accept_errors:
        _LOGGER.error("Please check the details in the configuration file")
        return False
    else:
        data = SnmpData(
            host, port, community, baseoid, version, accept_errors,
            default_value)
        add_devices([SnmpSensor(data, name, unit, value_template)], True)


class SnmpSensor(Entity):
    """Representation of a SNMP sensor."""

    def __init__(self, data, name, unit_of_measurement,
                 value_template):
        """Initialize the sensor."""
        self.data = data
        self._name = name
        self._state = None
        self._unit_of_measurement = unit_of_measurement
        self._value_template = value_template
        self._attributes = {}

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def icon(self):
        """Return the icon of the device."""
        return 'mdi:printer'

    @property
    def device_state_attributes(self):
        """Attributes."""
        return self._attributes

    def update(self):
        """Get the latest data and updates the states."""
        self.data.update()
        self._state = self.data.value
        self._attributes = {
            k: str(v[-1]) for k, v in self.data.attributes.items()
        }


class SnmpData(object):
    """Get the latest data and update the states."""

    def __init__(self, host, port, community, baseoid, version, accept_errors,
                 default_value):
        """Initialize the data object."""
        self._host = host
        self._port = port
        self._community = community
        self._baseoid = baseoid
        self._version = SNMP_VERSIONS[version]
        self._accept_errors = accept_errors
        self._default_value = default_value
        self.value = None
        self.attributes = {}

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data from the remote SNMP capable host."""
        from pysnmp.hlapi import (
            nextCmd, CommunityData, SnmpEngine, UdpTransportTarget,
            ContextData, ObjectType, ObjectIdentity)
        for errindication, errstatus, errindex, restable in nextCmd(
            SnmpEngine(),
            CommunityData(self._community, mpModel=self._version),
            UdpTransportTarget((self._host, self._port)),
            ContextData(),
            ObjectType(ObjectIdentity(self._baseoid))
        ):
            if errindication and not self._accept_errors:
                _LOGGER.error("SNMP error: %s", errindication)
            elif errstatus and not self._accept_errors:
                _LOGGER.error(
                    "SNMP error: %s at %s",
                    errstatus.prettyPrint(),
                    errindex and restable[-1][int(errindex) - 1] or '?'
                )
            elif (errindication or errstatus) and self._accept_errors:
                self.value = self._default_value
            else:
                for resrow in restable:
                    self.attributes[str(resrow[0])] = resrow

        self.value = self._default_value

        errors = self.attributes.get('1.3.6.1.2.1.25.3.5.1.2.1')
        if errors:
            code = errors[1].asNumbers()[0]
            if code != 0:
                _LOGGER.info('Error code: %s', errors[1].asNumbers())
                self.value = ERRORS.get(int(math.log(code, 2)))
                return

        status = self.attributes.get('1.3.6.1.2.1.25.3.5.1.1.1')
        if status:
            self.value = STATUS.get(status[-1])
