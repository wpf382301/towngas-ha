"""Tests for the Towngas configuration schemas."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import voluptuous as vol
from voluptuous_serialize import convert

from homeassistant.helpers import config_validation as cv

from custom_components.towngas.config_flow import (
    PASSWORD_SELECTOR,
    URL_SELECTOR,
    TowngasOptionsFlowHandler,
)
from custom_components.towngas.const import (
    CONF_FLARESOLVERR_URL,
    CONF_MINI_ACCOUNT_ID,
    CONF_MINI_API_TOKEN,
    CONF_MINI_API_URL,
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

    def test_password_selector_is_serializable(self) -> None:
        schema = vol.Schema({vol.Optional("mini_api_token"): PASSWORD_SELECTOR})

        serialized = convert(schema, custom_serializer=cv.custom_serializer)

        self.assertEqual(len(serialized), 1)
        self.assertEqual(
            serialized[0]["selector"]["text"]["type"], "password"
        )


class TowngasOptionsFlowTests(unittest.IsolatedAsyncioTestCase):
    """Test the actual options form that previously returned HTTP 500."""

    async def test_options_form_schema_is_serializable(self) -> None:
        entry = SimpleNamespace(
            options={},
            data={
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_FLARESOLVERR_URL: DEFAULT_FLARESOLVERR_URL,
                CONF_MINI_API_URL: "",
                CONF_MINI_ACCOUNT_ID: "",
                CONF_MINI_API_TOKEN: "",
            },
        )
        flow = TowngasOptionsFlowHandler(entry)

        result = await flow.async_step_init()
        serialized = convert(
            result["data_schema"], custom_serializer=cv.custom_serializer
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(len(serialized), 5)
        self.assertTrue(any("selector" in field for field in serialized))

    async def test_options_reject_incomplete_mini_program_config(self) -> None:
        entry = SimpleNamespace(options={}, data={})
        flow = TowngasOptionsFlowHandler(entry)

        result = await flow.async_step_init(
            {
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL,
                CONF_FLARESOLVERR_URL: DEFAULT_FLARESOLVERR_URL,
                CONF_MINI_API_URL: "https://mini.example.invalid/account",
                CONF_MINI_ACCOUNT_ID: "",
                CONF_MINI_API_TOKEN: "",
            }
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"]["base"], "mini_api_incomplete")

if __name__ == "__main__":
    unittest.main()
