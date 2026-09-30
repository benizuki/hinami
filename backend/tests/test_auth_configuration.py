from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.core.auth import (
    auth_enabled,
    local_client_is_allowed,
    validate_auth_configuration,
)
from backend.app.core.paths import LOCAL_DATA_DIR, REPO_ROOT_DIR


class AuthConfigurationTest(unittest.TestCase):
    def test_repository_root_is_independent_of_auth_module_folder_depth(self) -> None:
        expected_root = Path(__file__).resolve().parents[2]

        self.assertEqual(REPO_ROOT_DIR, expected_root)
        self.assertEqual(
            LOCAL_DATA_DIR,
            expected_root / "backend" / "app" / "data",
        )

    def test_oauth_is_enabled_on_non_local_bind(self) -> None:
        with patch.dict(
            os.environ,
            {
                "HINAMI_API_HOST": "0.0.0.0",
                "GOOGLE_OAUTH_CLIENT_ID": "client-id",
            },
            clear=True,
        ):
            validate_auth_configuration()
            self.assertTrue(auth_enabled())

    def test_auth_can_be_disabled_on_127_0_0_1(self) -> None:
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "127.0.0.1"},
            clear=True,
        ):
            validate_auth_configuration()
            self.assertFalse(auth_enabled())

    def test_missing_oauth_is_rejected_on_non_local_bind(self) -> None:
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "0.0.0.0"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "GOOGLE_OAUTH_CLIENT_ID"):
                validate_auth_configuration()

    def test_missing_oauth_is_rejected_when_bind_host_is_not_declared(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "HINAMI_API_HOST"):
                validate_auth_configuration()

    def test_localhost_name_is_not_treated_as_explicit_127_0_0_1(self) -> None:
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "localhost"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                validate_auth_configuration()

    def test_local_client_hosts_allow_container_bind_without_oauth(self) -> None:
        # Docker Composeでは0.0.0.0で待ち受け、接続元をゲートウェイに限る。
        with patch.dict(
            os.environ,
            {"HINAMI_API_HOST": "0.0.0.0", "HINAMI_LOCAL_CLIENT_HOSTS": "172.29.90.1"},
            clear=True,
        ):
            validate_auth_configuration()
            self.assertFalse(auth_enabled())

    def test_local_client_hosts_must_be_private_addresses(self) -> None:
        for value in ("8.8.8.8", "0.0.0.0", "example.com"):
            with self.subTest(value=value), patch.dict(
                os.environ,
                {"HINAMI_API_HOST": "0.0.0.0", "HINAMI_LOCAL_CLIENT_HOSTS": value},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "HINAMI_LOCAL_CLIENT_HOSTS"):
                    validate_auth_configuration()

    def test_local_client_hosts_are_rejected_with_oauth(self) -> None:
        with patch.dict(
            os.environ,
            {"GOOGLE_OAUTH_CLIENT_ID": "client-id", "HINAMI_LOCAL_CLIENT_HOSTS": "172.29.90.1"},
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "HINAMI_LOCAL_CLIENT_HOSTS"):
                validate_auth_configuration()

    def test_unauthenticated_mode_is_rejected_on_cloud(self) -> None:
        for key in ("K_SERVICE", "KUBERNETES_SERVICE_HOST", "GAE_ENV"):
            with self.subTest(key=key), patch.dict(
                os.environ,
                {"HINAMI_API_HOST": "127.0.0.1", key: "detected"},
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, key):
                    validate_auth_configuration()

    def test_only_loopback_and_declared_clients_are_allowed(self) -> None:
        with patch.dict(os.environ, {"HINAMI_LOCAL_CLIENT_HOSTS": "172.29.90.1"}, clear=True):
            for host in ("127.0.0.1", "::1", "172.29.90.1"):
                self.assertTrue(local_client_is_allowed(host), host)
            for host in (None, "", "172.29.90.2", "192.168.1.10", "localhost"):
                self.assertFalse(local_client_is_allowed(host), host)


if __name__ == "__main__":
    unittest.main()
