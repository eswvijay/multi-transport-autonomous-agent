from __future__ import annotations

import logging
import os
from typing import Any

import boto3
import requests

logger = logging.getLogger(__name__)

CLOUDAUTH_ENDPOINT = os.environ.get("CLOUDAUTH_ENDPOINT", "https://oauth.cloudauth.example.com")


class CloudAuthSession:
    def __init__(self, region: str | None = None):
        self._region = region or os.environ.get("AWS_REGION", "us-west-2")
        self._boto_session = boto3.Session(region_name=self._region)
        self._credentials = self._boto_session.get_credentials()
        self._access_token: str | None = None

    def _ensure_token(self) -> str:
        if self._access_token:
            return self._access_token

        frozen = self._credentials.get_frozen_credentials()
        auth_response = requests.post(
            f"{CLOUDAUTH_ENDPOINT}/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Amz-Security-Token": frozen.token or "",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "openid",
            },
            timeout=15,
        )

        if auth_response.status_code != 200:
            raise RuntimeError(f"CloudAuth token exchange failed: {auth_response.status_code} {auth_response.text[:200]}")

        self._access_token = auth_response.json().get("access_token", "")
        logger.info("CloudAuth token obtained successfully")
        return self._access_token

    def get_authorization(self, url: str, **kwargs: Any) -> requests.Response:
        token = self._ensure_token()
        return requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=kwargs.get("timeout", 10))

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, timeout: int = 30) -> requests.Response:
        token = self._ensure_token()
        merged_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if headers:
            merged_headers.update(headers)
        return requests.post(url, json=json, headers=merged_headers, timeout=timeout)

    def get(self, url: str, headers: dict | None = None, timeout: int = 30) -> requests.Response:
        token = self._ensure_token()
        merged_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            merged_headers.update(headers)
        return requests.get(url, headers=merged_headers, timeout=timeout)

    def test_connection(self) -> str:
        try:
            self._ensure_token()
            return "CloudAuth connection test successful"
        except requests.HTTPError as e:
            return f"CloudAuth test failed: HTTP {e.response.status_code}"
        except Exception as e:
            return f"CloudAuth test failed: {repr(e)}"


def create_cloudauth_session(region: str | None = None) -> CloudAuthSession:
    return CloudAuthSession(region)
