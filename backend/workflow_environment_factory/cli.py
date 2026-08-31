from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

import uvicorn

from .app import create_app
from .auth import load_or_create_token
from .config import Settings
from .engine import DockerEngine
from .services import Services

_MINIMUM_CODEX_VERSION = (0, 151, 0)


def codex_version_supported(output: str) -> bool:
    match = re.search(r"\bcodex-cli\s+(\d+)\.(\d+)\.(\d+)", output)
    return match is not None and tuple(int(part) for part in match.groups()) >= _MINIMUM_CODEX_VERSION


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wef", description="Workflow Environment Factory")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="start the loopback-only local product")
    subparsers.add_parser("doctor", help="check protocol schemas, Docker, Codex, and local paths")
    return parser


def doctor(settings: Settings) -> int:
    failures: list[str] = []
    try:
        for version in ("workflow.case.v1", "workflow.score.v1", "agent.run.v1"):
            settings.protocol_schema_dir.joinpath(f"{version}.schema.json").read_text(encoding="utf-8")
    except OSError as error:
        failures.append(f"protocol schemas: {error}")
    docker = DockerEngine(settings.docker_executable).availability()
    if docker.status != "pass":
        failures.append(f"Docker: {docker.stderr or docker.stdout or 'unavailable'}")
    codex_path = shutil.which(settings.codex_executable)
    codex_supported = False
    if codex_path is None:
        failures.append(f"Codex: executable not found: {settings.codex_executable}")
    else:
        codex = subprocess.run(
            [codex_path, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            shell=False,
            check=False,
        )
        if codex.returncode != 0:
            failures.append(f"Codex: {codex.stderr or codex.stdout or 'version check failed'}")
        elif not codex_version_supported(f"{codex.stdout}\n{codex.stderr}"):
            failures.append("Codex: version 0.151.0 or newer is required for fail-closed restricted reads")
        else:
            codex_supported = True
    print(f"Data directory: {settings.data_dir}")
    print(f"Protocol schemas: {settings.protocol_schema_dir}")
    print(f"Docker: {docker.status}")
    print(f"Codex: {'pass' if codex_supported else 'error'}")
    for failure in failures:
        print(f"FAIL {failure}")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> None:
    arguments = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[2]
    settings = Settings.load(repository_root, initialize=arguments.command != "doctor")
    if arguments.command == "doctor":
        raise SystemExit(doctor(settings))
    services = Services.build(settings)
    recovered = services.store.recover_interrupted_runs()
    token = load_or_create_token(settings.token_path)
    print(f"Workflow Environment Factory: http://{settings.host}:{settings.port}/session/{token}")
    print(f"Local data: {settings.data_dir}")
    if recovered:
        print(f"Recovered {len(recovered)} interrupted Run(s) as environment errors.")
    try:
        uvicorn.run(
            create_app(services),
            host=settings.host,
            port=settings.port,
            access_log=False,
            log_level="info",
        )
    finally:
        services.close()


if __name__ == "__main__":
    main()
