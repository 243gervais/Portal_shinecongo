import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { SERVICE_TYPES } from "../../lib/constants";
import { Notice } from "../../components/Ui";

export default function EmployeeWashFormPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const formData = new FormData(event.currentTarget);
      await apiFetch("/employee/lavages/", {
        method: "POST",
        data: formData,
      });
      navigate("/employe/lavage/mes-lavages/");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Lavage</p>
        <h1>Ajouter un lavage</h1>
        <p>Les photos restent obligatoires. Le portail conserve le flux actuel d&apos;upload.</p>
        {error ? <Notice type="error">{error}</Notice> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Type de service</span>
            <select name="type_service" defaultValue="COMPLET" required>
              {SERVICE_TYPES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Plaque</span>
            <input type="text" name="plaque" placeholder="AA-1234" />
          </label>

          <label className="field">
            <span>Photo de plaque</span>
            <input type="file" name="plaque_photo" accept="image/*" />
          </label>

          <label className="field">
            <span>Montant déclaré (FC)</span>
            <input type="number" name="montant" min="0" step="0.01" required />
          </label>

          <label className="field field-full">
            <span>Notes</span>
            <textarea name="notes" rows="4" placeholder="Détails facultatifs" />
          </label>

          <label className="field field-full">
            <span>Photos du lavage</span>
            <input type="file" name="photos" accept="image/*" multiple required />
          </label>

          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Enregistrement..." : "Enregistrer le lavage"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
