from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class GitResult:
    exit_code: int
    stdout: str
    stderr: str


class GitWorkspaceManager:
    def __init__(self, worktrees_root: Path):
        self.worktrees_root = worktrees_root.resolve()
        self.worktrees_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def run(repository: Path, arguments: list[str], timeout: int = 60) -> GitResult:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        return GitResult(completed.returncode, completed.stdout, completed.stderr)

    def inspect_repository(
        self, requested: str, base_revision: str, solution_revision: str
    ) -> tuple[Path, str, str, str]:
        requested_path = Path(requested).expanduser().resolve()
        root_result = self.run(requested_path, ["rev-parse", "--show-toplevel"])
        if root_result.exit_code != 0:
            raise ValueError(f"repository_path is not a Git repository: {root_result.stderr.strip()}")
        root = Path(root_result.stdout.strip()).resolve()
        if root != requested_path:
            raise ValueError("repository_path must be the Git repository root")
        base = self._resolve_commit(root, base_revision)
        solution = self._resolve_commit(root, solution_revision)
        if base == solution:
            raise ValueError("base and solution revisions must be different")
        ancestor = self.run(root, ["merge-base", "--is-ancestor", base, solution])
        if ancestor.exit_code != 0:
            raise ValueError("solution_revision must descend from base_revision in the 0.1 code factory")
        patch = self.run(root, ["diff", "--binary", base, solution], timeout=120)
        if patch.exit_code != 0 or not patch.stdout:
            raise ValueError("base-to-solution diff is empty or unavailable")
        return root, base, solution, f"sha256:{hashlib.sha256(patch.stdout.encode('utf-8')).hexdigest()}"

    def _resolve_commit(self, repository: Path, revision: str) -> str:
        result = self.run(repository, ["rev-parse", f"{revision}^{{commit}}"])
        if result.exit_code != 0:
            raise ValueError(f"could not resolve Git revision {revision}: {result.stderr.strip()}")
        return result.stdout.strip()

    def materialize(
        self,
        repository: Path,
        revision: str,
        namespace: UUID | str,
        name: str,
        original_value: str,
        replacement_value: str,
        variable_paths: list[str],
    ) -> tuple[Path, int]:
        safe_name = "".join(character for character in name if character.isalnum() or character in "-_")
        if not safe_name:
            raise ValueError("worktree name contains no safe characters")
        path = (self.worktrees_root / str(namespace) / safe_name).resolve()
        if self.worktrees_root not in path.parents:
            raise ValueError("worktree path escaped the product data directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        add = self.run(repository, ["worktree", "add", "--detach", str(path), revision], timeout=120)
        if add.exit_code != 0:
            raise RuntimeError(f"git worktree add failed: {add.stderr.strip()}")
        replacements = 0
        if replacement_value != original_value:
            for relative in variable_paths:
                target = (path / relative).resolve()
                if path not in target.parents or not target.is_file():
                    self.remove(repository, path)
                    raise ValueError(f"variable path is missing or unsafe: {relative}")
                text = target.read_text(encoding="utf-8")
                count = text.count(original_value)
                if count:
                    target.write_text(text.replace(original_value, replacement_value), encoding="utf-8")
                    replacements += count
            if replacements == 0:
                self.remove(repository, path)
                raise ValueError(f"variant value source {original_value!r} was not found in confirmed variable paths")
        return path, replacements

    def remove(self, repository: Path, path: Path) -> None:
        resolved = path.resolve()
        if self.worktrees_root not in resolved.parents:
            raise ValueError("refusing to remove a worktree outside the product data directory")
        remove = self.run(repository, ["worktree", "remove", "--force", str(resolved)], timeout=120)
        if remove.exit_code != 0 and resolved.exists():
            raise RuntimeError(f"git worktree cleanup failed: {remove.stderr.strip()}")
        prune = self.run(repository, ["worktree", "prune"], timeout=60)
        if prune.exit_code != 0:
            raise RuntimeError(f"git worktree prune failed: {prune.stderr.strip()}")

    def changed_paths(self, workspace: Path, base_revision: str) -> list[str]:
        result = self.run(workspace, ["diff", "--name-only", base_revision])
        if result.exit_code != 0:
            raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
        return [line.replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
