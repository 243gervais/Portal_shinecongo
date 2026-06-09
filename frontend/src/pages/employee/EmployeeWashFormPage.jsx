import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Notice } from "../../components/Ui";
import { SERVICE_TYPES } from "../../lib/constants";
import { apiFetch } from "../../lib/api";

function buildPreviewItem(file) {
  return {
    id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
    file,
    previewUrl: URL.createObjectURL(file),
  };
}

function normalizeImageFiles(fileList) {
  return Array.from(fileList || [])
    .filter((file) => file && file.type && file.type.startsWith("image/"))
    .map(buildPreviewItem);
}

export default function EmployeeWashFormPage() {
  const navigate = useNavigate();
  const washCameraInputRef = useRef(null);
  const washGalleryInputRef = useRef(null);
  const plaquePhotoInputRef = useRef(null);
  const plaquePhotoRef = useRef(null);
  const washPhotosRef = useRef([]);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
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

  function handlePlaquePhotoChange(event) {
    const nextPhoto = normalizeImageFiles(event.target.files)[0] || null;

    setPlaquePhoto((currentPhoto) => {
      if (currentPhoto?.previewUrl) {
        URL.revokeObjectURL(currentPhoto.previewUrl);
      }
      return nextPhoto;
    });

    event.target.value = "";
  }

  function addWashPhotos(fileList) {
    const nextPhotos = normalizeImageFiles(fileList);
    if (!nextPhotos.length) {
      return;
    }

    setWashPhotos((currentPhotos) => [...currentPhotos, ...nextPhotos]);
  }

  function handleWashCameraChange(event) {
    addWashPhotos(event.target.files);
    event.target.value = "";
  }

  function handleWashGalleryChange(event) {
    addWashPhotos(event.target.files);
    event.target.value = "";
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
    setBusy(true);
    setError("");

    if (!washPhotos.length) {
      setBusy(false);
      setError("Veuillez prendre ou choisir au moins une photo du lavage.");
      return;
    }

    try {
      const form = event.currentTarget;
      const formData = new FormData();
      formData.append("type_service", form.type_service.value);
      formData.append("plaque", (form.plaque.value || "").trim().toUpperCase());
      formData.append("montant", form.montant.value);
      formData.append("notes", form.notes.value || "");

      if (plaquePhoto?.file) {
        formData.append("plaque_photo", plaquePhoto.file);
      }

      washPhotos.forEach((photo) => {
        formData.append("photos", photo.file);
      });

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
        <p>Le bouton photo ouvre directement l&apos;appareil photo sur téléphone. Vous pouvez aussi choisir des images déjà présentes.</p>
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
              <button
                type="button"
                className="button button-primary"
                onClick={() => plaquePhotoInputRef.current?.click()}
              >
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

          <label className="field">
            <span>Montant déclaré (FC)</span>
            <input type="number" name="montant" min="0" step="0.01" required />
          </label>

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
              onChange={handleWashCameraChange}
              hidden
            />
            <input
              ref={washGalleryInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleWashGalleryChange}
              hidden
            />

            <div className="capture-button-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => washCameraInputRef.current?.click()}
              >
                Prendre une photo
              </button>
              <button
                type="button"
                className="button button-muted"
                onClick={() => washGalleryInputRef.current?.click()}
              >
                Choisir des photos
              </button>
            </div>

            <div className="capture-help">
              Le bouton photo ouvre directement l&apos;appareil photo du téléphone. Ajoutez autant de photos que nécessaire.
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
                <div className="capture-empty capture-empty-grid">
                  Aucune photo ajoutée pour le moment.
                </div>
              )}
            </div>
          </div>

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
