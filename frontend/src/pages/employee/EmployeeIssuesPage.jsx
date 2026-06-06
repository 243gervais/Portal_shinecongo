import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Pagination } from "../../components/Ui";

export default function EmployeeIssuesPage() {
  const [pageData, setPageData] = useState(null);
  const [error, setError] = useState("");

  async function load(page = 1) {
    try {
      setError("");
      const payload = await apiFetch("/employee/problemes/", {
        query: { page },
      });
      setPageData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (error) {
    return <ErrorState message={error} onRetry={() => load(pageData?.page || 1)} />;
  }

  if (!pageData) {
    return <LoadingState label="Chargement des problèmes..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Suivi</p>
            <h1>Mes problèmes</h1>
          </div>
          <Link className="button button-primary" to="/employe/probleme/signaler/">
            Nouveau signalement
          </Link>
        </div>

        <div className="list-stack">
          {pageData.results.map((issue) => (
            <Link key={issue.id} to={`/employe/probleme/${issue.id}/`} className="list-card">
              <ImageThumb src={issue.photo_thumbnail_url} alt={issue.categorie_display} />
              <div className="list-content">
                <h3>{issue.categorie_display}</h3>
                <p>{issue.created_at_display}</p>
                <p>Statut: {issue.statut_display}</p>
              </div>
            </Link>
          ))}
        </div>

        <Pagination pageData={pageData} onPageChange={load} />
      </section>
    </div>
  );
}
