from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "workflow.case.v1": "workflow.case.v1.schema.json",
    "workflow.score.v1": "workflow.score.v1.schema.json",
    "agent.run.v1": "agent.run.v1.schema.json",
}


class ProtocolValidationError(ValueError):
    pass


class ProtocolValidator:
    def __init__(self, schema_directory: Path):
        self.schema_directory = schema_directory
        self._validators: dict[str, Draft202012Validator] = {}

    def _validator(self, schema_version: str) -> Draft202012Validator:
        if schema_version not in SCHEMA_FILES:
            raise ProtocolValidationError(f"unsupported schema_version: {schema_version}")
        if schema_version not in self._validators:
            path = self.schema_directory / SCHEMA_FILES[schema_version]
            if not path.is_file():
                raise ProtocolValidationError(
                    f"RunCase Interchange schema is missing: {path}. "
                    "Run scripts/Sync-Protocol.ps1 before starting the product."
                )
            schema = json.loads(path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(schema)
            self._validators[schema_version] = Draft202012Validator(schema, format_checker=FormatChecker())
        return self._validators[schema_version]

    def errors(self, document: dict[str, Any]) -> list[str]:
        schema_version = document.get("schema_version")
        if not isinstance(schema_version, str):
            return ["$: schema_version is required"]
        try:
            validator = self._validator(schema_version)
        except ProtocolValidationError as error:
            return [f"$: {error}"]
        errors = []
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
            path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
            errors.append(f"{path}: {error.message}")
        return errors

    def validate(self, document: dict[str, Any]) -> None:
        errors = self.errors(document)
        if errors:
            raise ProtocolValidationError("\n".join(errors))
