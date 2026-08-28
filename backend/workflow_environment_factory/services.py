from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .content_store import ContentStore
from .engine import DockerEngine, ExecutionEngine
from .factory import CaseFactory
from .gitops import GitWorkspaceManager
from .protocol import ProtocolValidator
from .recording import RecordingService
from .runner import CodexRunner
from .scoring import ScoreService
from .simulator import IssuePrSimulator
from .store import FactoryStore


@dataclass
class Services:
    settings: Settings
    store: FactoryStore
    content_store: ContentStore
    protocol: ProtocolValidator
    git: GitWorkspaceManager
    engine: ExecutionEngine
    simulator: IssuePrSimulator
    recordings: RecordingService
    factory: CaseFactory
    scorer: ScoreService
    runner: CodexRunner

    @classmethod
    def build(cls, settings: Settings, engine: ExecutionEngine | None = None) -> Services:
        store = FactoryStore(settings.database_path)
        content_store = ContentStore(settings.content_dir)
        protocol = ProtocolValidator(settings.protocol_schema_dir)
        git = GitWorkspaceManager(settings.worktrees_dir)
        execution_engine = engine or DockerEngine(settings.docker_executable)
        simulator = IssuePrSimulator()
        recordings = RecordingService(store)
        factory = CaseFactory(
            store=store,
            content_store=content_store,
            protocol=protocol,
            git=git,
            engine=execution_engine,
            simulator=simulator,
        )
        scorer = ScoreService(
            store=store,
            content_store=content_store,
            protocol=protocol,
            git=git,
            engine=execution_engine,
            simulator=simulator,
        )
        return cls(
            settings=settings,
            store=store,
            content_store=content_store,
            protocol=protocol,
            git=git,
            engine=execution_engine,
            simulator=simulator,
            recordings=recordings,
            factory=factory,
            scorer=scorer,
            runner=CodexRunner(store, settings.codex_executable, port=settings.port),
        )

    def close(self) -> None:
        self.store.close()
