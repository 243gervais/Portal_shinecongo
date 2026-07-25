import React, { useEffect, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerWaterPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/eau/");
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSubmit() {
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch("/manager/eau/", {
        method: "POST",
        data: {},
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
    return <LoadingState label="Chargement du suivi d'eau..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Suivi eau</p>
        <h1>{data.site.nom}</h1>
        <p>Signalez l'achat d'eau du jour pour le site.</p>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <div className="status-grid">
          <article className="status-card">
            <span className="status-label">Achat du jour</span>
            <strong>{data.today_purchase ? "Déjà signalé" : "Non signalé"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Mois facturé</span>
            <strong>{data.billing_month_display}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Signalements du mois</span>
            <strong>{data.month_purchase_count}</strong>
          </article>
        </div>

        <button
          type="button"
          className="button button-primary"
          disabled={busy || Boolean(data.today_purchase)}
          onClick={handleSubmit}
        >
          {busy ? "Enregistrement..." : "Signaler l'achat d'eau du jour"}
        </button>
      </section>
    </div>
  );
}
