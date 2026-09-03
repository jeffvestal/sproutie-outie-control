"""URL-based token authentication with session cookie strategy.

Used by modems like ARRIS SB8200 (HTTPS firmware variant) that:
1. Accept base64-encoded credentials in the URL query parameter
2. Return a session cookie for subsequent requests
3. Require the session token appended to URLs for authenticated requests
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from ..base import AuthResult, AuthStrategy, get_cookie_safe
from ..types import AuthErrorType

if TYPE_CHECKING:
    import requests

    from ..configs import AuthConfig

_LOGGER = logging.getLogger(__name__)


class UrlTokenSessionStrategy(AuthStrategy):
<redacted>
    """URL-based token auth with session cookie strategy.

    Auth flow:
    1. Build base64 token from credentials
    2. Send login request with token in URL and Authorization header
    3. Extract session cookie from response
    4. Fetch data page with session token in URL
    5. Return authenticated HTML
    """

    def login(
        self,
        session: requests.Session,
        base_url: str,
        username: <redacted>
        password: <redacted>
        config: AuthConfig,
        verbose: bool = False,
    ) -> AuthResult:
        """Authenticate using URL-based token with session cookie.

        Args:
            session: requests.Session object (modified in-place)
            base_url: Modem base URL (e.g., "https://192.168.100.1")
            username: <redacted>
            password: <redacted>
            config: UrlTokenSessionConfig with auth parameters

        Returns:
            AuthResult with success status, response HTML, and error details.
        """
        if not username or not password:
<redacted>
            _LOGGER.debug("No credentials provided for URL token auth, skipping")
            return AuthResult.ok()

        from ..configs import UrlTokenSessionConfig

        if not isinstance(config, UrlTokenSessionConfig):
<redacted>
            _LOGGER.error("UrlTokenSessionStrategy requires UrlTokenSessionConfig")
            return AuthResult.fail(
                AuthErrorType.STRATEGY_NOT_CONFIGURED,
                "UrlTokenSessionStrategy requires UrlTokenSessionConfig",
            )

        try:
            # Build base64 token: <redacted>
            credentials = f"{username}:<redacted>
            token = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

            # Build login URL with token parameter
            login_url = f"{base_url}{config.login_page}?{config.login_prefix}{token}"
            _LOGGER.debug("URL token auth: <redacted>

            # Include Authorization header (required by some firmware)
            headers = {"Authorization": <redacted>

            # Make login request
            response = session.get(login_url, headers=headers, timeout=10, verify=False)

            if response.status_code != 200:
                _LOGGER.warning("URL token auth: <redacted>
                if response.status_code == 401:
                    return AuthResult.fail(
                        AuthErrorType.INVALID_CREDENTIALS,
                        "Invalid credentials (HTTP 401)",
                        response_html=response.text,
                    )
                return AuthResult.fail(
                    AuthErrorType.UNKNOWN_ERROR,
                    f"Login returned HTTP {response.status_code}",
                    response_html=response.text,
                )

            # Check if we got data directly in login response
            if config.success_indicator in response.text:
                _LOGGER.info("URL token auth: <redacted>
                return AuthResult.ok(response.text)

            # Try to get session token from cookie (handles duplicate cookies)
            session_token = get_cookie_safe(session, config.session_cookie_name)
            if not session_token:
<redacted>
                _LOGGER.warning("URL token auth: <redacted>
                return AuthResult.ok()  # Return success to allow fallback

            _LOGGER.debug("URL token auth: <redacted>

            # Fetch data page with session token
            data_url = f"{base_url}{config.data_page}?{config.token_prefix}{session_token}"
            data_response = session.get(data_url, headers=headers, timeout=10, verify=False)

            if data_response.status_code == 200 and config.success_indicator in data_response.text:
                _LOGGER.info("URL token auth: <redacted>
                return AuthResult.ok(data_response.text)

            _LOGGER.warning(
                "URL token auth: <redacted>
                data_response.status_code,
                config.success_indicator in data_response.text,
            )
            return AuthResult.ok()  # Return success to allow fallback

        except Exception as e:
            _LOGGER.error("URL token auth: <redacted>
            return AuthResult.fail(
                AuthErrorType.CONNECTION_FAILED,
                f"URL token auth error: <redacted>
            )
