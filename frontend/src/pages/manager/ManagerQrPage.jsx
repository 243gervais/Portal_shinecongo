import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerQrPage() {
  const { siteId } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [motif, setMotif] = useState("");

  async function load() {
    try {
      setError("");
      const payload = await apiFetch(`/manager/qr/${siteId}/`);
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, [siteId]);

  async function regenerate(event) {
    event.preventDefault();
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch(`/manager/qr/${siteId}/regenerate/`, {
        method: "POST",
        data: { motif },
      });
      setNotice(payload.message);
      setMotif("");
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
    return <LoadingState label="Chargement du QR..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">QR permanent</p>
        <h1>{data.site.nom}</h1>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <div className="qr-layout">
          <img src={data.qr_image} alt={`QR ${data.site.nom}`} className="qr-image" />
          <div className="qr-meta">
            <p>URL: {data.qr_url}</p>
            <p>Token: {data.site_token}</p>
            <p>
              GPS: {data.gps.actif ? `actif (${data.gps.rayon_autorisé_mètres} m)` : "désactivé"}
            </p>
            <button type="button" className="button button-muted" onClick={() => window.print()}>
              Imprimer
            </button>
          </div>
        </div>

        <form className="form-grid" onSubmit={regenerate}>
          <label className="field field-full">
            <span>Motif de régénération</span>
            <textarea rows="4" value={motif} onChange={(event) => setMotif(event.target.value)} required />
          </label>
          <div className="field-full form-actions">
            <button type="submit" className="button button-accent" disabled={busy}>
              {busy ? "Régénération..." : "Régénérer le token"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
