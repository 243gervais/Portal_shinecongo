import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState, Pagination } from "../../components/Ui";

export default function EmployeeWashesPage() {
  const [pageData, setPageData] = useState(null);
  const [error, setError] = useState("");

  async function load(page = 1) {
    try {
      setError("");
      const payload = await apiFetch("/employee/lavages/", {
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
    return <LoadingState label="Chargement des lavages..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Historique</p>
            <h1>Mes lavages</h1>
          </div>
          <Link className="button button-primary" to="/employe/lavage/ajouter/">
            Nouveau lavage
          </Link>
        </div>

        <div className="list-stack">
          {pageData.results.map((wash) => (
            <Link key={wash.id} to={`/employe/lavage/${wash.id}/`} className="list-card">
              <ImageThumb src={wash.preview_photo || wash.plaque_photo_thumbnail_url} alt={wash.type_service_display} />
              <div className="list-content">
                <h3>{wash.type_service_display}</h3>
                <p>{wash.date_display}</p>
                <p>{wash.photo_count} photo(s)</p>
                {wash.plaque ? <p>Plaque: {wash.plaque}</p> : null}
              </div>
            </Link>
          ))}
        </div>

        <Pagination pageData={pageData} onPageChange={load} />
      </section>
    </div>
  );
}
