import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState, Notice } from "../../components/Ui";

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
          <article className="status-card">
            <span className="status-label">Eau</span>
            <strong>{data.water_purchase_today ? "Signalée" : "Non signalée"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Carburant</span>
            <strong>{data.fuel_purchase_today ? "Signalé" : "Non signalé"}</strong>
          </article>
        </div>

        <div className="button-row">
          <Link className="button button-primary" to="/manager/lavage/ajouter/">
            Ajouter un lavage
          </Link>
          <Link className="button button-muted" to="/manager/eau/">
            Signaler eau
          </Link>
          <Link className="button button-muted" to="/manager/carburant/">
            Signaler carburant
          </Link>
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

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Lavages du jour</p>
            <h2>Photos et voitures enregistrées</h2>
          </div>
          <Link className="button button-primary" to="/manager/lavage/ajouter/">
            Nouveau lavage
          </Link>
        </div>
        {data.today_washes.length ? (
          <div className="list-stack">
            {data.today_washes_truncated ? (
              <p className="inline-muted">
                Affichage des {data.today_washes.length} derniers lavages. La liste complète reste disponible dans la section Lavages.
              </p>
            ) : null}
            {data.today_washes.map((wash) => (
              <article key={wash.id} className="list-card compact-card">
                <div className="list-content">
                  <h3>{wash.type_service_display}</h3>
                  <p>{wash.employee_name}</p>
                  <p>{wash.date_display}</p>
                  <p>{wash.photo_count} photo(s)</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Aucun lavage" description="Aucun lavage n'a encore été enregistré aujourd'hui." />
        )}
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Problèmes du jour</p>
            <h2>Signalements</h2>
          </div>
          <Link className="button button-muted" to="/manager/probleme/signaler/">
            Signaler
          </Link>
        </div>
        {data.today_issues.length ? (
          <div className="list-stack">
            {data.today_issues_truncated ? (
              <p className="inline-muted">
                Affichage des {data.today_issues.length} derniers problèmes. La liste complète reste disponible dans la section Problèmes.
              </p>
            ) : null}
            {data.today_issues.map((issue) => (
              <article key={issue.id} className="list-card compact-card">
                <div className="list-content">
                  <h3>{issue.categorie_display}</h3>
                  <p>{issue.employee_name}</p>
                  <p>{issue.statut_display}</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Aucun problème" description="Aucun problème n'a été signalé aujourd'hui." />
        )}
      </section>
    </div>
  );
}
