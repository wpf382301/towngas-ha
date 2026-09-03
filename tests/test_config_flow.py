"""Tests for the current-only Towngas configuration schema."""
from __future__ import annotations

import unittest

from homeassistant.helpers import config_validation as cv
from voluptuous_serialize import convert

from custom_components.towngas.config_flow import _schema, validate_connection_options
from custom_components.towngas.const import (
    CONF_ACCOUNT_ID,
    CONF_API_URL,
    CONF_AUTHORIZATION,
    CONF_UPDATE_INTERVAL,
)


class TowngasConfigFlowTests(unittest.TestCase):
    """Verify validation and frontend serialization."""

    def test_schema_contains_only_current_settings(self) -> None:
        serialized = convert(_schema({}), custom_serializer=cv.custom_serializer)

        self.assertEqual(
            {field["name"] for field in serialized},
            {CONF_API_URL, CONF_ACCOUNT_ID, CONF_AUTHORIZATION, CONF_UPDATE_INTERVAL},
        )
        self.assertEqual(
            next(field for field in serialized if field["name"] == CONF_AUTHORIZATION)["selector"]["text"]["type"],
            "password",
        )

    def test_captured_endpoint_is_normalized(self) -> None:
        errors: dict[str, str] = {}
        result = validate_connection_options(
            {
                CONF_API_URL: "https://rqjf.jnyuxia.com/api/gas/detail?id=25076",
                CONF_ACCOUNT_ID: "25076",
                CONF_AUTHORIZATION: "token",
                CONF_UPDATE_INTERVAL: 30,
            },
            errors,
        )

        self.assertFalse(errors)
        self.assertEqual(result[CONF_API_URL], "https://rqjf.jnyuxia.com")

    def test_credentials_are_required(self) -> None:
        errors: dict[str, str] = {}
        validate_connection_options(
            {
                CONF_API_URL: "https://example.invalid",
                CONF_ACCOUNT_ID: "",
                CONF_AUTHORIZATION: "",
                CONF_UPDATE_INTERVAL: 30,
            },
            errors,
        )

        self.assertEqual(errors[CONF_ACCOUNT_ID], "invalid_account_id")
        self.assertEqual(errors[CONF_AUTHORIZATION], "authorization_required")


if __name__ == "__main__":
    unittest.main()
