import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { BlueprintPage } from "./pages/BlueprintPage";
import { CaseFactoryPage } from "./pages/CaseFactoryPage";
import { RunsPage } from "./pages/RunsPage";
import type { Blueprint, CaseRecord, Meta, Recording, RunRecord } from "./types";
import { ErrorBanner, Shell, type PageKey } from "./ui";

function pageFromHash(): PageKey {
  const value = window.location.hash.replace(/^#\/?/, "");
  if (value === "cases" || value === "runs") return value;
  return "blueprint";
}

export function App() {
  const [page, setPage] = useState<PageKey>(pageFromHash);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [blueprints, setBlueprints] = useState<Blueprint[]>([]);
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [nextMeta, nextBlueprints, nextCases, nextRuns, nextRecordings] = await Promise.all([
        api.meta(),
        api.blueprints(),
        api.cases(),
        api.runs(),
        api.recordings()
      ]);
      setMeta(nextMeta);
      setBlueprints(nextBlueprints);
      setCases(nextCases);
      setRuns(nextRuns);
      setRecordings(nextRecordings);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = (next: PageKey) => {
    window.location.hash = next;
    setPage(next);
  };

  return (
    <Shell page={page} meta={meta} onNavigate={navigate}>
      {error ? <ErrorBanner message={error} onDismiss={() => setError("")} /> : null}
      {loading ? (
        <div className="loading-page" aria-live="polite">
          Loading local factory…
        </div>
      ) : null}
      {!loading && page === "blueprint" ? (
        <BlueprintPage
          blueprints={blueprints}
          recordings={recordings}
          onChanged={refresh}
          onContinue={() => navigate("cases")}
          onError={setError}
        />
      ) : null}
      {!loading && page === "cases" ? (
        <CaseFactoryPage
          blueprints={blueprints}
          cases={cases}
          onChanged={refresh}
          onContinue={() => navigate("runs")}
          onError={setError}
        />
      ) : null}
      {!loading && page === "runs" ? (
        <RunsPage cases={cases} runs={runs} onChanged={refresh} onError={setError} />
      ) : null}
    </Shell>
  );
}
