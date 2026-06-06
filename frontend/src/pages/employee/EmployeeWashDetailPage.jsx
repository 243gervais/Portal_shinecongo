import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, ImageThumb, LoadingState } from "../../components/Ui";

export default function EmployeeWashDetailPage() {
  const { lavageId } = useParams();
  const [wash, setWash] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const payload = await apiFetch(`/employee/lavages/${lavageId}/`);
        if (!cancelled) {
          setWash(payload);
        }
      } catch (requestError) {
        if (!cancelled) {
          setError(requestError.message);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [lavageId]);

  if (error) {
    return <ErrorState message={error} onRetry={() => window.location.reload()} />;
  }

  if (!wash) {
    return <LoadingState label="Chargement du lavage..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Détail</p>
        <h1>{wash.type_service_display}</h1>
        <div className="detail-grid">
          <div>
            <p>Date: {wash.date_display}</p>
            <p>Créé le: {wash.created_at_display}</p>
            {wash.plaque ? <p>Plaque: {wash.plaque}</p> : null}
            {wash.notes ? <p>Notes: {wash.notes}</p> : null}
          </div>
          <ImageThumb
            src={wash.plaque_photo_url || wash.plaque_photo_thumbnail_url}
            alt="Plaque"
            large
          />
        </div>
      </section>

      <section className="section-card">
        <h2>Photos</h2>
        <div className="image-grid">
          {wash.photos.map((photo) => (
            <a key={photo.id} href={photo.url} target="_blank" rel="noreferrer" className="image-card">
              <ImageThumb src={photo.thumbnail_url} alt={photo.type_photo_display} large />
              <span>{photo.type_photo_display}</span>
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}
