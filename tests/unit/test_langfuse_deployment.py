import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="팀 서버는 POSIX 셸을 사용합니다"
)

DEPLOY = Path(__file__).resolve().parents[2] / "deploy" / "langfuse"
SECRETS = {
    "NEXTAUTH_SECRET",
    "SALT",
    "ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "CLICKHOUSE_PASSWORD",
    "REDIS_AUTH",
    "MINIO_ROOT_PASSWORD",
}


def test_init_env_permissions_and_no_overwrite(tmp_path):
    script = shutil.copy(DEPLOY / "init-env.sh", tmp_path)
    subprocess.run(["sh", script], cwd=tmp_path.parent, check=True)
    path = tmp_path / ".env"
    before = path.read_bytes()
    values = dict(line.split("=", 1) for line in before.decode().splitlines())
    assert values.pop("LANGFUSE_HOST") == ""
    assert values.keys() == SECRETS
    assert all(re.fullmatch("[0-9a-f]{64}", value) for value in values.values())
    assert len(set(values.values())) == len(SECRETS)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    result = subprocess.run(["sh", script], cwd=tmp_path.parent, check=False)
    assert result.returncode != 0
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".env.tmp.*"))


def test_init_env_generator_failure_leaves_no_file(tmp_path):
    script = shutil.copy(DEPLOY / "init-env.sh", tmp_path)
    fake = tmp_path / "openssl"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o700)
    result = subprocess.run(
        ["sh", script], env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    )
    assert result.returncode != 0
    assert not (tmp_path / ".env").exists()
    assert not list(tmp_path.glob(".env.tmp.*"))


@pytest.mark.parametrize(
    ("host", "valid"),
    [
        ("team.example.org", True),
        ("team-2.xn--3e0b707e", True),
        ("", False),
        ("https://team.example.org", False),
        ("team.example.org:443", False),
        ("team.example.org/path", False),
        ("first..last", False),
        ("-team.example.org", False),
        ("a" * 64 + ".org", False),
        (".".join(["a" * 63] * 4), False),
    ],
)
def test_deployment_host_validation(host, valid):
    result = subprocess.run(
        ["sh", DEPLOY / "validate-host.sh"],
        env={"PATH": os.environ["PATH"], "LANGFUSE_HOST": host},
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is valid
    if not valid:
        assert "LANGFUSE_HOST" in result.stderr


@pytest.mark.parametrize(
    "with_email", [False, True], ids=["without-email", "with-email"]
)
def test_compose_deployment(tmp_path, with_email):
    if not shutil.which("docker"):
        pytest.skip("Docker CLI is required to render the deployment manifest")
    for filename in ("compose.yaml", "validate-host.sh"):
        shutil.copy(DEPLOY / filename, tmp_path)
    env = {key: "0" * 64 for key in SECRETS}
    env.update(PATH=os.environ["PATH"], LANGFUSE_HOST="team.example.org")
    email = {
        "SMTP_CONNECTION_URL": "smtps://user:test%2Bvalue@mail.example.org:465",
        "EMAIL_FROM_ADDRESS": "langfuse@example.org",
    }
    if with_email:
        (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in email.items()))
    config = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    services = json.loads(config.stdout)["services"]
    for name in ("proxy", "langfuse-web", "langfuse-worker"):
        assert (
            services[name]["depends_on"]["validate-host"]["condition"]
            == "service_completed_successfully"
        )
    for name, service in services.items():
        for key, value in email.items():
            expected = (
                value
                if with_email and name in {"langfuse-web", "langfuse-worker"}
                else None
            )
            assert service.get("environment", {}).get(key) == expected
    gate = services["validate-host"]
    (mount,) = gate["volumes"]
    assert Path(mount["source"]).resolve() == (tmp_path / "validate-host.sh").resolve()
    assert mount["read_only"]
    assert gate["entrypoint"] == ["sh", mount["target"]]
    assert gate["environment"] == {"LANGFUSE_HOST": "team.example.org"}
    assert set(name for name, s in services.items() if s.get("ports")) == {"proxy"}
    assert {p["published"] for p in services["proxy"]["ports"]} == {"80", "443"}
