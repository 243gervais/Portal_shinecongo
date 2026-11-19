import React, { useState } from "react";
import { useNavigate } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { preparePhoto } from "../../lib/images";
import { ISSUE_CATEGORIES } from "../../lib/constants";
import { Notice } from "../../components/Ui";

export default function ManagerIssueFormPage() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");

    try {
      const formData = new FormData(event.currentTarget);
      const photo = formData.get("photo");
      if (photo?.size) formData.set("photo", await preparePhoto(photo));
      await apiFetch("/manager/problemes/", {
        method: "POST",
        data: formData,
        onUploadProgress: setProgress,
      });
      navigate("/manager/problemes/");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Problème site</p>
        <h1>Signaler un problème</h1>
        {error ? <Notice type="error">{error}</Notice> : null}
        {busy ? <p role="status">Préparation et envoi du signalement : {progress} %</p> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Catégorie</span>
            <select name="categorie" defaultValue="MATERIEL" required>
              {ISSUE_CATEGORIES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field field-full">
            <span>Description</span>
            <textarea name="description" rows="5" required />
          </label>

          <label className="field field-full">
            <span>Photo facultative</span>
            <input type="file" name="photo" accept="image/*" />
          </label>

          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Envoi..." : "Envoyer le signalement"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
