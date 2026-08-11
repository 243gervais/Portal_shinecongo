import React, { useEffect, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerFuelPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [amountValue, setAmountValue] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/carburant/");
      setData(payload);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function handleSubmit(event) {
    event.preventDefault();
    if (data.today_purchase) {
      setNotice("L'achat de carburant du jour a déjà été signalé.");
      return;
    }
    setNotice("");
    setPreviewOpen(true);
  }

  async function confirmSubmit() {
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch("/manager/carburant/", {
        method: "POST",
        data: {
          amount_fc: amountValue,
        },
      });
      setNotice(payload.message);
      setAmountValue("");
      setPreviewOpen(false);
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
    return <LoadingState label="Chargement du suivi carburant..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Suivi carburant</p>
        <h1>{data.site.nom}</h1>
        <p>Signalez l'achat de carburant du jour. Le montant est envoyé à l'administration, mais il n'est pas affiché dans l'historique manager.</p>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <div className="status-grid">
          <article className="status-card">
            <span className="status-label">Achat du jour</span>
            <strong>{data.today_purchase ? "Déjà signalé" : "Non signalé"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Mois rattaché</span>
            <strong>{data.billing_month_display}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Signalements du mois</span>
            <strong>{data.month_purchase_count}</strong>
          </article>
        </div>

        {previewOpen ? (
          <div className="preview-panel">
            <p className="eyebrow">Aperçu avant envoi</p>
            <h2>Confirmer le signalement carburant</h2>
            <div className="preview-grid">
              <div><strong>Site</strong><span>{data.site.nom}</span></div>
              <div><strong>Date</strong><span>{data.today}</span></div>
              <div><strong>Mois rattaché</strong><span>{data.billing_month_display}</span></div>
              <div><strong>Montant</strong><span>{amountValue || "0"} FC</span></div>
            </div>
            <div className="button-row">
              <button type="button" className="button button-primary" onClick={confirmSubmit} disabled={busy}>
                {busy ? "Enregistrement..." : "Confirmer et signaler une seule fois"}
              </button>
              <button type="button" className="button button-muted" onClick={() => setPreviewOpen(false)} disabled={busy}>
                Modifier
              </button>
            </div>
          </div>
        ) : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Prix du carburant acheté (FC)</span>
            <input
              type="number"
              min="1"
              step="0.01"
              inputMode="decimal"
              value={amountValue}
              onChange={(event) => setAmountValue(event.target.value)}
              disabled={busy || Boolean(data.today_purchase)}
              required
            />
          </label>

          <div className="field-full form-actions">
            <button
              type="submit"
              className="button button-primary"
              disabled={busy || Boolean(data.today_purchase)}
            >
              {data.today_purchase ? "Carburant déjà signalé" : busy ? "Enregistrement..." : "Voir l'aperçu avant envoi"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
