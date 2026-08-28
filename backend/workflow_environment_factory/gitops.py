from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import time
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
    def _clean_git_environment() -> dict[str, str]:
        environment = os.environ.copy()
        for key in tuple(environment):
            if key.upper().startswith("GIT_"):
                environment.pop(key, None)
        environment.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
        return environment

    @staticmethod
    def run(repository: Path, arguments: list[str], timeout: int = 60) -> GitResult:
        completed = subprocess.run(
            ["git", "-C", str(repository), *arguments],
            env=GitWorkspaceManager._clean_git_environment(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
        return GitResult(completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def isolated_git_dir(workspace: Path) -> Path:
        return (workspace.resolve().parent / "git-state").resolve()

    @classmethod
    def isolated_environment(cls, workspace: Path) -> dict[str, str]:
        environment = cls._clean_git_environment()
        environment.update(
            {
                "GIT_DIR": str(cls.isolated_git_dir(workspace)),
                "GIT_WORK_TREE": str(workspace.resolve()),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_ATTR_NOSYSTEM": "1",
            }
        )
        return environment

    @classmethod
    def run_isolated(cls, workspace: Path, arguments: list[str], timeout: int = 60) -> GitResult:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=workspace,
            env=cls.isolated_environment(workspace),
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
        patch = self.run(root, ["diff", "--no-ext-diff", "--no-textconv", "--binary", base, solution], timeout=120)
        if patch.exit_code != 0 or not patch.stdout:
            raise ValueError("base-to-solution diff is empty or unavailable")
        return root, base, solution, f"sha256:{hashlib.sha256(patch.stdout.encode('utf-8')).hexdigest()}"

    def _resolve_commit(self, repository: Path, revision: str) -> str:
        result = self.run(repository, ["rev-parse", f"{revision}^{{commit}}"])
        if result.exit_code != 0:
            raise ValueError(f"could not resolve Git revision {revision}: {result.stderr.strip()}")
        return result.stdout.strip()

    def _managed_path(self, namespace: UUID | str, name: str) -> Path:
        safe_name = "".join(character for character in name if character.isalnum() or character in "-_")
        if not safe_name:
            raise ValueError("workspace name contains no safe characters")
        path = (self.worktrees_root / str(namespace) / safe_name).resolve()
        if self.worktrees_root not in path.parents:
            raise ValueError("workspace path escaped the product data directory")
        return path

    def _apply_variant(
        self,
        path: Path,
        original_value: str,
        replacement_value: str,
        variable_paths: list[str],
    ) -> int:
        replacements = 0
        if replacement_value == original_value:
            return replacements
        for relative in variable_paths:
            target = (path / relative).resolve()
            if path not in target.parents or not target.is_file():
                raise ValueError(f"variable path is missing or unsafe: {relative}")
            text = target.read_text(encoding="utf-8")
            count = text.count(original_value)
            if count:
                target.write_text(text.replace(original_value, replacement_value), encoding="utf-8")
                replacements += count
        if replacements == 0:
            raise ValueError(f"variant value source {original_value!r} was not found in confirmed variable paths")
        return replacements

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
        path = self._managed_path(namespace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        add = self.run(
            repository,
            [
                "-c",
                f"core.hooksPath={self.worktrees_root / '.disabled-hooks'}",
                "worktree",
                "add",
                "--detach",
                str(path),
                revision,
            ],
            timeout=120,
        )
        if add.exit_code != 0:
            raise RuntimeError(f"git worktree add failed: {add.stderr.strip()}")
        try:
            return path, self._apply_variant(path, original_value, replacement_value, variable_paths)
        except Exception:
            self.remove(repository, path)
            raise

    def materialize_isolated(
        self,
        repository: Path,
        revision: str,
        namespace: UUID | str,
        name: str,
        original_value: str,
        replacement_value: str,
        variable_paths: list[str],
    ) -> tuple[Path, int]:
        """Create an Agent-visible repository without source refs or shared Git objects."""
        path = self._managed_path(namespace, name)
        git_dir = self.isolated_git_dir(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or git_dir.exists():
            raise FileExistsError("isolated workspace path already exists")
        try:
            path.mkdir(parents=False, exist_ok=False)
            self._initialize_isolated_repository(path, repository, revision)
            replacements = self._apply_variant(path, original_value, replacement_value, variable_paths)
            self._commit_isolated_baseline(path)
            return path, replacements
        except Exception:
            if path.exists() or git_dir.exists():
                self.remove_isolated(path)
            raise

    def _initialize_isolated_repository(self, path: Path, repository: Path, revision: str) -> None:
        git_dir = self.isolated_git_dir(path)
        initialized = self.run(
            path,
            ["-c", "init.templateDir=", "init", "--bare", "--initial-branch=main", str(git_dir)],
            timeout=120,
        )
        if initialized.exit_code != 0:
            raise RuntimeError(f"git init failed: {initialized.stderr.strip()}")
        commands = [
            (["config", "core.bare", "false"], "git work-tree configuration"),
            (["config", "core.worktree", str(path)], "git work-tree configuration"),
            (["config", "core.autocrlf", "false"], "git line-ending configuration"),
            (["config", "core.symlinks", "true"], "git symbolic-link configuration"),
            (["config", "core.hooksPath", str(git_dir / "disabled-hooks")], "git hook isolation"),
            (["config", "commit.gpgSign", "false"], "git signing isolation"),
        ]
        for arguments, label in commands:
            result = self.run_isolated(path, arguments, timeout=120)
            if result.exit_code != 0:
                raise RuntimeError(f"{label} failed: {result.stderr.strip()}")
        fetched = self.run_isolated(
            path,
            [
                "-c",
                "protocol.file.allow=always",
                "fetch",
                "--depth=1",
                "--no-tags",
                "--no-recurse-submodules",
                "--no-write-fetch-head",
                repository.resolve().as_uri(),
                f"{revision}:refs/wef/base",
            ],
            timeout=120,
        )
        if fetched.exit_code != 0:
            raise RuntimeError(f"isolated base fetch failed: {fetched.stderr.strip()}")
        reset = self.run_isolated(path, ["reset", "--hard", "refs/wef/base"], timeout=120)
        if reset.exit_code != 0:
            raise RuntimeError(f"isolated base checkout failed: {reset.stderr.strip()}")
        delete_temporary_ref = self.run_isolated(path, ["update-ref", "-d", "refs/wef/base"])
        if delete_temporary_ref.exit_code != 0:
            raise RuntimeError(f"isolated temporary-ref cleanup failed: {delete_temporary_ref.stderr.strip()}")
        gitlinks = self.run_isolated(path, ["ls-files", "--stage"])
        if gitlinks.exit_code != 0:
            raise RuntimeError(f"isolated submodule scan failed: {gitlinks.stderr.strip()}")
        if any(line.startswith("160000 ") for line in gitlinks.stdout.splitlines()):
            raise ValueError("Git submodules are not supported in isolated 0.1 Agent workspaces")
        root = path.resolve()
        for directory, directory_names, file_names in os.walk(root, followlinks=False):
            for name in [*directory_names, *file_names]:
                candidate = Path(directory, name)
                if candidate.is_symlink():
                    target = candidate.resolve(strict=False)
                    if target != root and root not in target.parents:
                        raise ValueError(f"symbolic link escapes the isolated workspace: {candidate.relative_to(root)}")

    def _commit_isolated_baseline(self, path: Path) -> None:
        commands = [
            (["config", "user.name", "Workflow Environment Factory"], "git user configuration"),
            (["config", "user.email", "factory@example.invalid"], "git user configuration"),
            (["add", "--all"], "git add"),
            (
                ["commit", "--allow-empty", "--no-verify", "--no-gpg-sign", "-m", "Factory isolated baseline"],
                "git baseline commit",
            ),
        ]
        for arguments, label in commands:
            result = self.run_isolated(path, arguments, timeout=120)
            if result.exit_code != 0:
                raise RuntimeError(f"{label} failed: {result.stderr.strip()}")

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

    def remove_isolated(self, path: Path) -> None:
        resolved = path.resolve()
        if self.worktrees_root not in resolved.parents:
            raise ValueError("refusing to remove an isolated workspace outside the product data directory")

        def make_writable_and_retry(function, target: str, _: object) -> None:
            os.chmod(target, stat.S_IWRITE)
            function(target)

        cleanup_errors: list[str] = []
        for target in (resolved, self.isolated_git_dir(resolved)):
            if not target.exists():
                continue
            last_error: OSError | None = None
            for attempt in range(5):
                try:
                    shutil.rmtree(target, onerror=make_writable_and_retry)
                    last_error = None
                    break
                except OSError as error:
                    if not target.exists():
                        last_error = None
                        break
                    last_error = error
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                cleanup_errors.append(f"{target}: {last_error}")
        if cleanup_errors:
            raise RuntimeError(f"isolated workspace cleanup failed: {'; '.join(cleanup_errors)}")

    def changed_paths(self, workspace: Path, base_revision: str) -> list[str]:
        result = self.run_isolated(workspace, ["diff", "--name-only", base_revision])
        if result.exit_code != 0:
            raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
        untracked = self.run_isolated(workspace, ["ls-files", "--others", "--exclude-standard"])
        if untracked.exit_code != 0:
            raise RuntimeError(f"git untracked-file scan failed: {untracked.stderr.strip()}")
        paths = {
            line.replace("\\", "/")
            for output in (result.stdout, untracked.stdout)
            for line in output.splitlines()
            if line.strip()
        }
        return sorted(paths)
