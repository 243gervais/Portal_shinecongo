import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState } from "../../components/Ui";

export default function ManagerDashboardPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState({
    date_debut: "",
    date_fin: "",
  });

  async function load(nextFilters = filters) {
    try {
      setError("");
      const payload = await apiFetch("/manager/dashboard/", {
        query: nextFilters,
      });
      setData(payload);
      setFilters({
        date_debut: payload.date_debut,
        date_fin: payload.date_fin,
      });
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load({ date_debut: "", date_fin: "" });
  }, []);

  if (error) {
    return <ErrorState message={error} onRetry={() => load()} />;
  }

  if (!data) {
    return <LoadingState label="Chargement du dashboard manager..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Pilotage</p>
            <h1>Dashboard manager</h1>
          </div>
        </div>

        <form
          className="filter-grid"
          onSubmit={(event) => {
            event.preventDefault();
            load(filters);
          }}
        >
          <label className="field">
            <span>Date début</span>
            <input
              type="date"
              value={filters.date_debut}
              onChange={(event) => setFilters({ ...filters, date_debut: event.target.value })}
            />
          </label>
          <label className="field">
            <span>Date fin</span>
            <input
              type="date"
              value={filters.date_fin}
              onChange={(event) => setFilters({ ...filters, date_fin: event.target.value })}
            />
          </label>
          <div className="field form-actions-inline">
            <button type="submit" className="button button-primary">Appliquer</button>
          </div>
        </form>
        <p className="inline-muted">Période chargée: {data.selected_period_label}</p>
      </section>

      <section className="stats-grid stats-grid-wide">
        {data.sites.map((site) => (
          <article key={site.site_id} className="stat-card stat-card-wide">
            <div className="stat-card-head">
              <h2>{site.site_name}</h2>
              <Link className="button button-muted" to={`/manager/qr/${site.site_id}/`}>
                QR
              </Link>
            </div>
            <div className="mini-stats">
              <div><strong>{site.presents}</strong><span>Présents</span></div>
              <div><strong>{site.absents}</strong><span>Absents</span></div>
              <div><strong>{site.missed_punch}</strong><span>Sorties manquantes</span></div>
              <div><strong>{site.total_lavages}</strong><span>Lavages</span></div>
              {data.can_view_money ? (
                <div><strong>{site.revenue_display}</strong><span>Chiffre</span></div>
              ) : null}
              <div><strong>{site.problemes_ouverts}</strong><span>Problèmes</span></div>
            </div>
            <div className="button-row">
              <Link className="button button-primary" to={`/manager/pointages/?site=${site.site_id}`}>
                Pointages
              </Link>
              <Link className="button button-primary" to={`/manager/lavages/?site=${site.site_id}`}>
                Lavages
              </Link>
              <Link className="button button-accent" to={`/manager/problemes/?site=${site.site_id}`}>
                Problèmes
              </Link>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
