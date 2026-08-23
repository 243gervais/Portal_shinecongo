import React, { useEffect, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

export default function ManagerWaterPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [supplierChoice, setSupplierChoice] = useState("honosha");
  const [otherSupplierName, setOtherSupplierName] = useState("");
  const [otherAmountFc, setOtherAmountFc] = useState("");

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/eau/");
      setData(payload);
      setSupplierChoice((currentChoice) =>
        payload.supplier_options?.some((option) => option.value === currentChoice)
          ? currentChoice
          : payload.supplier_options?.[0]?.value || "honosha",
      );
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function handleSubmit() {
    if (data.today_purchase) {
      setNotice("L'achat d'eau du jour a déjà été signalé.");
      return;
    }
    if (!supplierChoice) {
      setNotice("Choisissez le fournisseur d'eau.");
      return;
    }
    if (supplierChoice === "other") {
      if (!otherSupplierName.trim()) {
        setNotice("Saisissez le nom du fournisseur.");
        return;
      }
      if (!otherAmountFc || Number(otherAmountFc) <= 0) {
        setNotice("Saisissez le prix de l'eau acheté.");
        return;
      }
    }
    setNotice("");
    setPreviewOpen(true);
  }

  async function confirmSubmit() {
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch("/manager/eau/", {
        method: "POST",
        data: {
          supplier_choice: supplierChoice,
          other_supplier_name: supplierChoice === "other" ? otherSupplierName.trim() : "",
          amount_fc: supplierChoice === "other" ? otherAmountFc : "",
        },
      });
      setNotice(payload.message);
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
    return <LoadingState label="Chargement du suivi d'eau..." />;
  }
  const selectedSupplier = data.supplier_options?.find((option) => option.value === supplierChoice);

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

        {!data.today_purchase ? (
          <div className="section-card-subtle">
            <p className="eyebrow">Fournisseur</p>
            <div className="filter-grid">
              <label className="field">
                <span>Où l'eau a été achetée ?</span>
                <select
                  value={supplierChoice}
                  onChange={(event) => {
                    setSupplierChoice(event.target.value);
                    setPreviewOpen(false);
                    setNotice("");
                  }}
                >
                  {data.supplier_options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              {supplierChoice === "other" ? (
                <>
                  <label className="field">
                    <span>Nom du fournisseur</span>
                    <input
                      type="text"
                      value={otherSupplierName}
                      onChange={(event) => setOtherSupplierName(event.target.value)}
                      placeholder="Nom du fournisseur"
                    />
                  </label>
                  <label className="field">
                    <span>Prix payé (FC)</span>
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={otherAmountFc}
                      onChange={(event) => setOtherAmountFc(event.target.value)}
                      placeholder="Ex: 22000"
                    />
                  </label>
                </>
              ) : null}
            </div>
          </div>
        ) : null}

        {previewOpen ? (
          <div className="preview-panel">
            <p className="eyebrow">Aperçu avant envoi</p>
            <h2>Confirmer le signalement d'eau</h2>
            <div className="preview-grid">
              <div><strong>Site</strong><span>{data.site.nom}</span></div>
              <div><strong>Date</strong><span>{data.today}</span></div>
              <div><strong>Mois facturé</strong><span>{data.billing_month_display}</span></div>
              <div><strong>Fournisseur</strong><span>{supplierChoice === "other" ? otherSupplierName : selectedSupplier?.label}</span></div>
              {supplierChoice === "other" ? (
                <div><strong>Prix payé</strong><span>{otherAmountFc} FC</span></div>
              ) : null}
            </div>
            <div className="button-row">
              <button type="button" className="button button-primary" onClick={confirmSubmit} disabled={busy}>
                {busy ? "Enregistrement..." : "Confirmer et signaler une seule fois"}
              </button>
              <button type="button" className="button button-muted" onClick={() => setPreviewOpen(false)} disabled={busy}>
                Annuler
              </button>
            </div>
          </div>
        ) : null}

        <button
          type="button"
          className="button button-primary"
          disabled={busy || Boolean(data.today_purchase)}
          onClick={handleSubmit}
        >
          {data.today_purchase ? "Eau déjà signalée" : busy ? "Enregistrement..." : "Voir l'aperçu avant envoi"}
        </button>
      </section>
    </div>
  );
}
