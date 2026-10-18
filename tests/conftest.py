"""Test against a private real Redis instance, never the developer's configured Redis."""

import shutil
import subprocess
import time

import pytest
from redis import Redis
from redis.exceptions import RedisError


@pytest.fixture(scope="session")
def redis_url(tmp_path_factory):
    root = tmp_path_factory.mktemp("private-redis")
    root.chmod(0o777)
    socket = root / "redis.sock"
    executable = shutil.which("redis-server")
    container = f"job-scraper-tests-{root.name}-{__import__('os').getpid()}"
    if executable:
        args = [
            executable,
            "--port",
            "0",
            "--unixsocket",
            str(socket),
            "--unixsocketperm",
            "700",
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(root),
        ]
    elif shutil.which("docker"):
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            container,
            "--network=none",
            "-v",
            f"{root}:/redis-test",
            "redis:8-alpine",
            "redis-server",
            "--port",
            "0",
            "--unixsocket",
            "/redis-test/redis.sock",
            "--unixsocketperm",
            "777",
            "--save",
            "",
            "--appendonly",
            "no",
        ]
    else:
        pytest.fail("Tests require redis-server or Docker; docker build --target test also works")
    log = (root / "server.log").open("w+")
    process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    url = "unix://" + str(socket)
    try:
        for _ in range(100):
            if process.poll() is not None:
                log.seek(0)
                pytest.fail("Private Redis failed to start: " + log.read())
            try:
                with Redis.from_url(url) as client:
                    client.ping()
                break
            except RedisError:
                time.sleep(0.1)
        else:
            pytest.fail("Private Redis startup timed out; pull redis:8-alpine first")
        yield url
    finally:
        if executable:
            process.terminate()
        else:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        process.wait(timeout=15)
        log.close()


@pytest.fixture(autouse=True)
def private_redis(monkeypatch, redis_url):
    monkeypatch.setenv("REDIS_URL", redis_url)
    # This URL belongs exclusively to the temporary server created above.
    with Redis.from_url(redis_url) as client:
        client.flushdb()
    yield redis_url
