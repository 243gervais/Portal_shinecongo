import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Pagination } from "../../components/Ui";

export default function ManagerProblemesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const currentFilters = {
    page: searchParams.get("page") || "1",
    site: searchParams.get("site") || "",
    statut: searchParams.get("statut") || "",
    categorie: searchParams.get("categorie") || "",
  };

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/problemes/", {
        query: currentFilters,
      });
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, [searchParams]);

  if (error) {
    return <ErrorState message={error} onRetry={load} />;
  }

  if (!data) {
    return <LoadingState label="Chargement des problèmes..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Problèmes</p>
        <h1>Problèmes signalés</h1>

        <div className="filter-grid">
          <label className="field">
            <span>Site</span>
            <select
              value={currentFilters.site}
              onChange={(event) => setSearchParams({ ...currentFilters, site: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.sites.map((site) => (
                <option key={site.id} value={site.id}>
                  {site.nom}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Statut</span>
            <select
              value={currentFilters.statut}
              onChange={(event) => setSearchParams({ ...currentFilters, statut: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.statuts.map((statut) => (
                <option key={statut.value} value={statut.value}>
                  {statut.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Catégorie</span>
            <select
              value={currentFilters.categorie}
              onChange={(event) => setSearchParams({ ...currentFilters, categorie: event.target.value, page: "1" })}
            >
              <option value="">Toutes</option>
              {data.filters.categories.map((category) => (
                <option key={category.value} value={category.value}>
                  {category.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="list-stack">
          {data.results.map((issue) => (
            <article key={issue.id} className="list-card">
              <ImageThumb src={issue.photo_thumbnail_url} alt={issue.categorie_display} />
              <div className="list-content">
                <h3>{issue.categorie_display}</h3>
                <p>{issue.employee_name}</p>
                <p>{issue.site_name}</p>
                <p>{issue.created_at_display}</p>
                <p>Statut: {issue.statut_display}</p>
              </div>
            </article>
          ))}
        </div>

        <Pagination
          pageData={data}
          onPageChange={(page) => setSearchParams({ ...currentFilters, page: String(page) })}
        />
      </section>
    </div>
  );
}
