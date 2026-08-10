"""Tests for the Towngas configuration schemas."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import voluptuous as vol
from voluptuous_serialize import convert

from homeassistant.helpers import config_validation as cv

from custom_components.towngas.config_flow import (
    URL_SELECTOR,
    TowngasOptionsFlowHandler,
)
from custom_components.towngas.const import (
    CONF_FLARESOLVERR_URL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FLARESOLVERR_URL,
    DEFAULT_UPDATE_INTERVAL,
)


class TowngasConfigSchemaTests(unittest.TestCase):
    """Verify schemas are compatible with Home Assistant's frontend."""

    def test_url_validator_is_serializable(self) -> None:
        schema = vol.Schema({vol.Optional("flaresolverr_url"): URL_SELECTOR})

        serialized = convert(schema, custom_serializer=cv.custom_serializer)

        self.assertEqual(len(serialized), 1)
        self.assertIn("selector", serialized[0])


class TowngasOptionsFlowTests(unittest.IsolatedAsyncioTestCase):
    """Test the actual options form that previously returned HTTP 500."""

    async def test_options_form_schema_is_serializable(self) -> None:
        entry = SimpleNamespace(
            options={},
            data={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_FLARESOLVERR_URL: DEFAULT_FLARESOLVERR_URL,
            },
        )
        flow = TowngasOptionsFlowHandler(entry)

        result = await flow.async_step_init()
        serialized = convert(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(len(serialized), 2)
        self.assertTrue(any("selector" in field for field in serialized))

if __name__ == "__main__":
    unittest.main()
