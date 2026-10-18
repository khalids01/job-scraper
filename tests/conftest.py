"""Use private real MongoDB and Redis servers, never configured production services."""

import os
import shutil
import subprocess
import time
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import PyMongoError
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


@pytest.fixture(scope="session")
def mongo_server(tmp_path_factory):
    """Start an isolated real MongoDB, ignoring all production connection variables."""
    root = tmp_path_factory.mktemp("private-mongo")
    container = f"job-scraper-mongo-tests-{os.getpid()}"
    executable = shutil.which("mongod")
    process = None
    if executable:
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = (root / "server.log").open("w+")
        process = subprocess.Popen(
            [
                executable,
                "--dbpath",
                str(root),
                "--bind_ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--wiredTigerCacheSizeGB",
                "0.25",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    else:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "-p",
                "127.0.0.1::27017",
                "mongo:7.0",
                "--wiredTigerCacheSizeGB",
                "0.25",
            ],
            check=True,
            capture_output=True,
        )
        mapping = subprocess.check_output(["docker", "port", container, "27017"], text=True)
        port = int(mapping.strip().rsplit(":", 1)[1])
    url = f"mongodb://127.0.0.1:{port}"
    client = MongoClient(url, serverSelectionTimeoutMS=200)
    try:
        for _ in range(150):
            if process and process.poll() is not None:
                log.seek(0)
                pytest.fail("Private MongoDB exited: " + log.read())
            if not process:
                running = subprocess.check_output(
                    ["docker", "inspect", "--format", "{{.State.Running}}", container], text=True
                ).strip()
                if running != "true":
                    pytest.fail(
                        "Private MongoDB exited: "
                        + subprocess.check_output(["docker", "logs", container], text=True)
                    )
            try:
                client.admin.command("ping")
                break
            except PyMongoError:
                time.sleep(0.1)
        else:
            pytest.fail("Private MongoDB startup timed out")
        yield url
    finally:
        client.close()
        if process:
            process.terminate()
            process.wait(timeout=30)
            log.close()
        else:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)


@pytest.fixture(autouse=True)
def mongodb_url(monkeypatch, mongo_server):
    database = "test_" + uuid4().hex
    url = mongo_server + "/" + database
    monkeypatch.setenv("MONGODB_URL", url)
    yield url
    with MongoClient(mongo_server) as client:
        client.drop_database(database)
