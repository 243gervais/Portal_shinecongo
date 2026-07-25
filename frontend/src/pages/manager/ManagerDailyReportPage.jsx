import React, { useEffect, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerDailyReportPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState("");

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/rapport-journalier/");
      setData(payload);
      setNotes(payload.report_notes || "");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch("/manager/rapport-journalier/", {
        method: "POST",
        data: {
          date: data.date,
          site: data.site.id,
          notes,
        },
      });
      setNotice(payload.message);
      await load();
    } catch (requestError) {
      setNotice(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Chargement du rapport manager..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Rapport manager</p>
        <h1>{data.site.nom}</h1>
        <p>Rapport opérationnel du {data.date}. Aucun montant n'est affiché dans ce portail.</p>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <div className="status-grid">
          <article className="status-card">
            <span className="status-label">Lavages du jour</span>
            <strong>{data.total_lavages}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Problèmes signalés</span>
            <strong>{data.issue_count}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Statut</span>
            <strong>{data.report_submitted ? "Envoyé" : "Non envoyé"}</strong>
          </article>
        </div>

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field field-full">
            <span>Notes opérationnelles</span>
            <textarea
              rows="5"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Présence, incidents, remarques clients ou matériel..."
            />
          </label>
          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Envoi..." : data.report_submitted ? "Mettre à jour le rapport" : "Envoyer le rapport"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
