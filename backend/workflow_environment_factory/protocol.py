from __future__ import annotations

import calendar
import ipaddress
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES = {
    "workflow.case.v1": "workflow.case.v1.schema.json",
    "workflow.score.v1": "workflow.score.v1.schema.json",
    "agent.run.v1": "agent.run.v1.schema.json",
}


FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("date-time")
def _date_time(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})[Tt\s](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?"
        r"(?:[Zz]|([+-])(\d{2})(?::?(\d{2}))?)",
        value,
        re.ASCII,
    )
    if not match:
        return False
    year, month, day, hour, minute, second = map(int, match.groups()[:6])
    direction, offset_hour, offset_minute = match.groups()[6:]
    oh, om = int(offset_hour or 0), int(offset_minute or 0)
    if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(year, month)[1]:
        return False
    if hour > 23 or minute > 59 or oh > 23 or om > 59:
        return False
    offset = (oh * 60 + om) * (-1 if direction == "-" else 1)
    return second < 60 or (second == 60 and (hour * 60 + minute - offset) % 1440 == 1439)


_URI_CHARS = r"(?:[A-Za-z0-9._~!$&'()*+,;=-]|%[0-9A-Fa-f]{2})"
_URI_PATH = re.compile(rf"(?:{_URI_CHARS}|[:@/])*")
_URI_QUERY = re.compile(rf"(?:{_URI_CHARS}|[:@/?])*")
_URI_AUTHORITY = re.compile(rf"(?:((?:{_URI_CHARS}|:)*)@)?(\[[^\]]+\]|(?:{_URI_CHARS})*)(?::[0-9]*)?")


@FORMAT_CHECKER.checks("uri", raises=ValueError)
def _uri(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value) or re.search(r"[^\x21-\x7e]", value):
        return False
    parts = urlsplit(value)
    authority = _URI_AUTHORITY.fullmatch(parts.netloc)
    if not authority:
        return False
    host = authority[2]
    if host.startswith("[") and not re.fullmatch(rf"\[v[0-9a-fA-F]+\.(?:{_URI_CHARS}|:)+\]", host, re.I):
        ipaddress.IPv6Address(host[1:-1])
    return bool(
        _URI_PATH.fullmatch(parts.path) and _URI_QUERY.fullmatch(parts.query) and _URI_QUERY.fullmatch(parts.fragment)
    )


def _semantic_errors(doc: dict[str, Any]) -> list[str]:
    errors = []
    if doc["schema_version"] == "workflow.score.v1":
        result = doc["task_result"]
        required = [row for row in doc["validations"] if row["required"]]
        if result["status"] == "pass" and (
            not any(row["objective"] for row in required) or any(row["status"] != "pass" for row in required)
        ):
            errors.append("$.task_result.status: pass requires objective evidence and all required validations to pass")
        if result["status"] == "not_scored" and "score" in result:
            errors.append("$.task_result.score: not_scored must omit the numeric score")
    elif doc["schema_version"] == "agent.run.v1":
        covered = {gap.get("source") for gap in doc["capture"]["gaps"]}
        for index, source in enumerate(doc["capture"]["sources"]):
            if source["status"] == "unavailable" and source["name"] not in covered:
                errors.append(f"$.capture.sources[{index}].status: unavailable source needs a named gap")
    else:
        types = {"identifier": (str,), "path": (str,), "string": (str,), "number": (int, float), "boolean": (bool,)}
        for index, item in enumerate(doc["variables"]):
            kind = item["value_type"]
            if kind != "json" and type(item["value"]) not in types[kind]:
                errors.append(f"$.variables[{index}].value: value must match its declared type {kind}")
    return errors


class ProtocolValidationError(ValueError):
    pass


class ProtocolValidator:
    def __init__(self, schema_directory: Path, *, semantic: bool = False):
        self.semantic = semantic
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
            self._validators[schema_version] = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
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
        return _semantic_errors(document) if self.semantic and not errors else errors

    def validate(self, document: dict[str, Any]) -> None:
        errors = self.errors(document)
        if errors:
            raise ProtocolValidationError("\n".join(errors))
