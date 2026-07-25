import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Pagination } from "../../components/Ui";

export default function ManagerLavagesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");

  const currentFilters = {
    page: searchParams.get("page") || "1",
    site: searchParams.get("site") || "",
    employe: searchParams.get("employe") || "",
    type_service: searchParams.get("type_service") || "",
    date_debut: searchParams.get("date_debut") || "",
    date_fin: searchParams.get("date_fin") || "",
  };

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/lavages/", {
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
    return <LoadingState label="Chargement des lavages..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Lavages</p>
            <h1>Suivi des lavages</h1>
          </div>
          <div className="hero-pill">{data.totals.count} lavage(s)</div>
        </div>

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
            <span>Service</span>
            <select
              value={currentFilters.type_service}
              onChange={(event) => setSearchParams({ ...currentFilters, type_service: event.target.value, page: "1" })}
            >
              <option value="">Tous</option>
              {data.filters.types_service.map((service) => (
                <option key={service.value} value={service.value}>
                  {service.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="list-stack">
          {data.results.map((wash) => (
            <article key={wash.id} className="list-card">
              <ImageThumb src={wash.preview_photo || wash.plaque_photo_thumbnail_url} alt={wash.type_service_display} />
              <div className="list-content">
                <h3>{wash.type_service_display}</h3>
                <p>{wash.employee_name}</p>
                <p>{wash.site_name}</p>
                <p>{wash.date_display}</p>
                {data.can_view_money && wash.amount_display ? <p>{wash.amount_display}</p> : null}
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
