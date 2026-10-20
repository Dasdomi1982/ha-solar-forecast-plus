"""Shared fixtures (pytest-homeassistant-custom-component)."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading the integration from custom_components."""
    yield
