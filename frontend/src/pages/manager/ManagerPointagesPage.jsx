import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Pagination } from "../../components/Ui";

export default function ManagerPointagesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const currentFilters = {
    page: searchParams.get("page") || "1",
    site: searchParams.get("site") || "",
    employe: searchParams.get("employe") || "",
    date_debut: searchParams.get("date_debut") || "",
    date_fin: searchParams.get("date_fin") || "",
  };

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/pointages/", {
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
    return <LoadingState label="Chargement des pointages..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Pointages</p>
        <h1>Liste des pointages</h1>

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
            <span>Employé</span>
            <select
              value={currentFilters.employe}
              onChange={(event) => setSearchParams({ ...currentFilters, employe: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.employees.map((employee) => (
                <option key={employee.id} value={employee.id}>
                  {employee.nom}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Date début</span>
            <input
              type="date"
              value={currentFilters.date_debut}
              onChange={(event) => setSearchParams({ ...currentFilters, date_debut: event.target.value, page: "1" })}
            />
          </label>
          <label className="field">
            <span>Date fin</span>
            <input
              type="date"
              value={currentFilters.date_fin}
              onChange={(event) => setSearchParams({ ...currentFilters, date_fin: event.target.value, page: "1" })}
            />
          </label>
        </div>

        <div className="list-stack">
          {data.results.map((item) => (
            <article key={item.id} className="list-card compact-card">
              <div className="list-content">
                <h3>{item.employee_name}</h3>
                <p>{item.site_name}</p>
                <p>{item.date_display}</p>
                <p>Entrée: {item.clock_in_display || "--:--"} | Sortie: {item.clock_out_display || "--:--"}</p>
              </div>
              <Link className="button button-primary" to={`/manager/pointages/${item.id}/corriger/`}>
                Corriger
              </Link>
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
