import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState } from "../../components/Ui";

export default function EmployeeIssueDetailPage() {
  const { problemeId } = useParams();
  const [issue, setIssue] = useState(null);
  const [error, setError] = useState("");

  async function load(signal) {
    try {
      setError("");
      const payload = await apiFetch(`/employee/problemes/${problemeId}/`, { signal });
      setIssue(payload);
    } catch (requestError) {
      if (requestError.name !== "AbortError") {
        setError(requestError.message);
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => {
      controller.abort();
    };
  }, [problemeId]);

  if (error) {
    return <ErrorState message={error} onRetry={() => load()} />;
  }

  if (!issue) {
    return <LoadingState label="Chargement du signalement..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Détail</p>
        <h1>{issue.categorie_display}</h1>
        <p>Signalé le {issue.created_at_display}</p>
        <p>Statut: {issue.statut_display}</p>
        <p>{issue.description}</p>
        {issue.notes_resolution ? <p>Résolution: {issue.notes_resolution}</p> : null}
      </section>

      {issue.photo_url ? (
        <section className="section-card">
          <h2>Photo jointe</h2>
          <a href={issue.photo_url} target="_blank" rel="noreferrer">
            <ImageThumb src={issue.photo_thumbnail_url || issue.photo_url} alt={issue.categorie_display} large />
          </a>
        </section>
      ) : null}
    </div>
  );
}
