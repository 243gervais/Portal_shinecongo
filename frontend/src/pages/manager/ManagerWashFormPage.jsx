import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Notice } from "../../components/Ui";
import { SERVICE_TYPES } from "../../lib/constants";
import { apiFetch } from "../../lib/api";
import { preparePhotoSelection } from "../../lib/images";

export default function ManagerWashFormPage() {
  const navigate = useNavigate();
  const washCameraInputRef = useRef(null);
  const washGalleryInputRef = useRef(null);
  const plaquePhotoInputRef = useRef(null);
  const plaquePhotoRef = useRef(null);
  const washPhotosRef = useRef([]);
  const submissionId = useRef(crypto.randomUUID());
  const submitting = useRef(false);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preparing, setPreparing] = useState(0);
  const [progress, setProgress] = useState(0);
  const [plaquePhoto, setPlaquePhoto] = useState(null);
  const [washPhotos, setWashPhotos] = useState([]);

  useEffect(() => {
    plaquePhotoRef.current = plaquePhoto;
  }, [plaquePhoto]);

  useEffect(() => {
    washPhotosRef.current = washPhotos;
  }, [washPhotos]);

  useEffect(() => (
    () => {
      if (plaquePhotoRef.current?.previewUrl) {
        URL.revokeObjectURL(plaquePhotoRef.current.previewUrl);
      }
      washPhotosRef.current.forEach((photo) => {
        URL.revokeObjectURL(photo.previewUrl);
      });
    }
  ), []);

  async function handlePlaquePhotoChange(event) {
    const files = Array.from(event.target.files || []).slice(0, 1);
    event.target.value = "";
    setPreparing(count => count + 1);
    const { items, errors } = await preparePhotoSelection(files);
    setPreparing(count => count - 1);
    setError(errors.join(" "));
    const nextPhoto = items[0];
    if (!nextPhoto) return;
    setPlaquePhoto((currentPhoto) => {
      if (currentPhoto?.previewUrl) {
        URL.revokeObjectURL(currentPhoto.previewUrl);
      }
      return nextPhoto;
    });
  }

  async function addWashPhotos(fileList) {
    if (washPhotosRef.current.length + fileList.length > 19) {
      setError("Ajoutez au maximum 19 photos de lavage et une photo de plaque.");
      return;
    }
    setPreparing(count => count + 1);
    const { items: nextPhotos, errors } = await preparePhotoSelection(fileList);
    setPreparing(count => count - 1);
    setError(errors.join(" "));
    if (nextPhotos.length) {
      setWashPhotos((currentPhotos) => [...currentPhotos, ...nextPhotos]);
    }
  }

  function removeWashPhoto(photoId) {
    setWashPhotos((currentPhotos) => {
      const targetPhoto = currentPhotos.find((photo) => photo.id === photoId);
      if (targetPhoto?.previewUrl) {
        URL.revokeObjectURL(targetPhoto.previewUrl);
      }
      return currentPhotos.filter((photo) => photo.id !== photoId);
    });
  }

  function clearPlaquePhoto() {
    setPlaquePhoto((currentPhoto) => {
      if (currentPhoto?.previewUrl) {
        URL.revokeObjectURL(currentPhoto.previewUrl);
      }
      return null;
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (submitting.current || preparing) return;
    submitting.current = true;
    setBusy(true);
    setProgress(0);
    setError("");

    if (!washPhotos.length) {
      setBusy(false);
      submitting.current = false;
      setError("Veuillez prendre ou choisir au moins une photo du lavage.");
      return;
    }

    try {
      const form = event.currentTarget;
      const formData = new FormData();
      formData.append("submission_id", submissionId.current);
      formData.append("type_service", form.type_service.value);
      formData.append("plaque", (form.plaque.value || "").trim().toUpperCase());
      formData.append("notes", form.notes.value || "");

      if (plaquePhoto?.file) {
        formData.append("plaque_photo", plaquePhoto.file);
      }
      washPhotos.forEach((photo) => {
        formData.append("photos", photo.file);
      });

      await apiFetch("/manager/lavages/", {
        method: "POST",
        data: formData,
        onUploadProgress: setProgress,
      });
      navigate("/manager/lavages/");
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Lavage manager</p>
        <h1>Ajouter un lavage</h1>
        <p>Ajoutez les photos du lavage. Aucun montant n'est demandé dans le portail manager.</p>
        {error ? <Notice type="error">{error}</Notice> : null}
        <p role="status" aria-live="polite">{preparing ? "Préparation et réduction des photos…" : busy ? progress < 100 ? `Envoi des photos : ${progress} %` : "Photos transmises. Enregistrement en cours…" : "Les photos sont réduites automatiquement avant l'envoi."}</p>

        <form className="form-grid" onSubmit={handleSubmit}>
          <fieldset disabled={busy || preparing > 0} style={{ display: "contents" }}>
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

          <div className="field field-full">
            <span>Photo de plaque</span>
            <input
              ref={plaquePhotoInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={handlePlaquePhotoChange}
              hidden
            />
            <div className="capture-button-row">
              <button type="button" className="button button-primary" onClick={() => plaquePhotoInputRef.current?.click()}>
                Prendre la photo de la plaque
              </button>
              {plaquePhoto ? (
                <button type="button" className="button button-muted" onClick={clearPlaquePhoto}>
                  Supprimer la photo
                </button>
              ) : null}
            </div>
            <div className="capture-preview capture-preview-single">
              {plaquePhoto ? (
                <img src={plaquePhoto.previewUrl} alt="Photo de plaque" className="capture-preview-image" />
              ) : (
                <div className="capture-empty">Aucune photo de plaque sélectionnée.</div>
              )}
            </div>
          </div>

          <label className="field field-full">
            <span>Notes</span>
            <textarea name="notes" rows="4" placeholder="Détails facultatifs" />
          </label>

          <div className="field field-full">
            <span>Photos du lavage</span>
            <input
              ref={washCameraInputRef}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(event) => {
                addWashPhotos(event.target.files);
                event.target.value = "";
              }}
              hidden
            />
            <input
              ref={washGalleryInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={(event) => {
                addWashPhotos(event.target.files);
                event.target.value = "";
              }}
              hidden
            />

            <div className="capture-button-row">
              <button type="button" className="button button-primary" onClick={() => washCameraInputRef.current?.click()}>
                Prendre une photo
              </button>
              <button type="button" className="button button-muted" onClick={() => washGalleryInputRef.current?.click()}>
                Choisir des photos
              </button>
            </div>

            <div className="capture-preview-grid">
              {washPhotos.length ? (
                washPhotos.map((photo, index) => (
                  <article key={photo.id} className="capture-preview-card">
                    <button
                      type="button"
                      className="capture-remove"
                      onClick={() => removeWashPhoto(photo.id)}
                      aria-label={`Retirer la photo ${index + 1}`}
                    >
                      ×
                    </button>
                    <img src={photo.previewUrl} alt={`Photo lavage ${index + 1}`} className="capture-preview-image" />
                    <div className="capture-preview-label">Photo {index + 1}</div>
                  </article>
                ))
              ) : (
                <div className="capture-empty capture-empty-grid">Aucune photo ajoutée pour le moment.</div>
              )}
            </div>
          </div>

          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy || preparing > 0}>
              {busy ? "Enregistrement..." : "Enregistrer le lavage"}
            </button>
          </div>
          </fieldset>
        </form>
      </section>
    </div>
  );
}
