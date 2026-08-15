import React, { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { apiFetch } from "../../lib/api";
import { EmptyState, ErrorState, LoadingState, Notice } from "../../components/Ui";

function CustomExpenseRow({ value, index, onChange, onRemove, disabled = false }) {
  return (
    <div className="expense-row">
      <input
        type="text"
        value={value.label}
        placeholder="Nom de la dépense"
        disabled={disabled}
        onChange={(event) => onChange(index, "label", event.target.value)}
      />
      <input
        type="number"
        value={value.amount_value}
        placeholder="Montant FC"
        min="0"
        step="0.01"
        disabled={disabled}
        onChange={(event) => onChange(index, "amount_value", event.target.value)}
      />
      <button type="button" className="button button-muted" onClick={() => onRemove(index)} disabled={disabled}>
        Retirer
      </button>
    </div>
  );
}

function normalizeCustomExpense(expense, clientId) {
  return {
    clientId,
    label: expense?.label || "",
    amount_value: expense?.amount_value || "",
  };
}

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

export default function ManagerDailyReportPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState("");
  const [knownExpenses, setKnownExpenses] = useState([]);
  const [customExpenses, setCustomExpenses] = useState([]);
  const [declaredAmount, setDeclaredAmount] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [equipmentPhotos, setEquipmentPhotos] = useState({});
  const customExpenseIdRef = useRef(0);
  const equipmentPhotosRef = useRef({});

  function createCustomExpense(expense = {}) {
    const clientId = `manager-custom-expense-${customExpenseIdRef.current}`;
    customExpenseIdRef.current += 1;
    return normalizeCustomExpense(expense, clientId);
  }

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/manager/rapport-journalier/");
      setData(payload);
      setNotes(payload.report_notes || "");
      setKnownExpenses(payload.expense_form?.known || []);
      setCustomExpenses((payload.expense_form?.custom || []).map((expense) => createCustomExpense(expense)));
      setDeclaredAmount(payload.submitted_total_amount || "");
      setEquipmentPhotos({});
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    equipmentPhotosRef.current = equipmentPhotos;
  }, [equipmentPhotos]);

  useEffect(() => (
    () => {
      Object.values(equipmentPhotosRef.current).flat().forEach((photo) => {
        if (photo.previewUrl) {
          URL.revokeObjectURL(photo.previewUrl);
        }
      });
    }
  ), []);

  function updateKnownExpense(index, field, value) {
    const next = [...knownExpenses];
    next[index] = {
      ...next[index],
      [field]: value,
    };
    setKnownExpenses(next);
  }

  function updateCustomExpense(index, field, value) {
    setCustomExpenses((currentExpenses) => {
      const next = [...currentExpenses];
      next[index] = {
        ...next[index],
        [field]: value,
      };
      return next;
    });
  }

  function removeCustomExpense(index) {
    setCustomExpenses((currentExpenses) => currentExpenses.filter((_, expenseIndex) => expenseIndex !== index));
  }

  function addEquipmentPhotos(machineId, fileList) {
    const nextPhotos = normalizeImageFiles(fileList);
    if (!nextPhotos.length) {
      return;
    }
    setEquipmentPhotos((currentPhotos) => ({
      ...currentPhotos,
      [machineId]: [...(currentPhotos[machineId] || []), ...nextPhotos],
    }));
  }

  function removeEquipmentPhoto(machineId, photoId) {
    setEquipmentPhotos((currentPhotos) => {
      const targetPhoto = (currentPhotos[machineId] || []).find((photo) => photo.id === photoId);
      if (targetPhoto?.previewUrl) {
        URL.revokeObjectURL(targetPhoto.previewUrl);
      }
      return {
        ...currentPhotos,
        [machineId]: (currentPhotos[machineId] || []).filter((photo) => photo.id !== photoId),
      };
    });
  }

  function missingEquipmentPhotos() {
    if (data.report_submitted) {
      return [];
    }
    return (data.equipment_checklist || []).filter((machine) => !(equipmentPhotos[machine.id] || []).length);
  }

  function selectedExpenseRows() {
    return [
      ...knownExpenses
        .filter((expense) => expense.selected)
        .map((expense) => ({
          label: expense.label,
          amount: expense.amount_value || "0",
        })),
      ...customExpenses
        .filter((expense) => expense.label || expense.amount_value)
        .map((expense) => ({
          label: expense.label || "Dépense sans nom",
          amount: expense.amount_value || "0",
        })),
    ];
  }

  function buildFormData() {
    const formData = new FormData();
    formData.append("date", data.date);
    formData.append("site", data.site.id);
    formData.append("notes", notes);
    formData.append("total_amount_reported_fc", declaredAmount);
    knownExpenses.forEach((expense) => {
      if (expense.selected) {
        formData.append(`known_expense_${expense.key}_enabled`, "1");
      }
      formData.append(`known_expense_${expense.key}_amount`, expense.amount_value || "");
    });
    customExpenses.forEach((expense) => {
      formData.append("custom_expense_label", expense.label || "");
      formData.append("custom_expense_amount", expense.amount_value || "");
    });
    Object.entries(equipmentPhotos).forEach(([machineId, photos]) => {
      photos.forEach((photo) => {
        formData.append("equipment_photo_machine_id", machineId);
        formData.append("equipment_photo", photo.file);
      });
    });
    return formData;
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (data.report_submitted) {
      setNotice("Le rapport final du jour a déjà été envoyé. Contactez l'administrateur pour une correction.");
      return;
    }
    const missingMachines = missingEquipmentPhotos();
    if (missingMachines.length) {
      setNotice(`Ajoutez au moins une photo de fin de journée pour: ${missingMachines.map((machine) => machine.name).join(", ")}.`);
      return;
    }
    setNotice("");
    setPreviewOpen(true);
  }

  async function confirmSubmit() {
    setBusy(true);
    setNotice("");
    try {
      const payload = await apiFetch("/manager/rapport-journalier/", {
        method: "POST",
        data: buildFormData(),
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
    return <LoadingState label="Chargement du rapport manager..." />;
  }

  const expensePreviewRows = selectedExpenseRows();
  const equipmentChecklist = data.equipment_checklist || [];
  const missingMachines = missingEquipmentPhotos();

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Rapport manager</p>
        <h1>{data.site.nom}</h1>
        <p>
          Rapport opérationnel du {data.date}: lavages, total de la journée, dépenses, eau, carburant et présences.
        </p>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <div className="status-grid">
          <article className="status-card">
            <span className="status-label">Lavages du jour</span>
            <strong>{data.total_lavages}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Problèmes signalés</span>
            <strong>{data.issue_count}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Statut</span>
            <strong>{data.report_submitted ? "Envoyé" : "Non envoyé"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Montant déclaré</span>
            <strong>{data.submitted_total_amount ? `${data.submitted_total_amount} FC` : "À saisir"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Présents</span>
            <strong>{data.attendance_count}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Eau</span>
            <strong>{data.water_purchase_today ? "Signalée" : "Non signalée"}</strong>
          </article>
          <article className="status-card">
            <span className="status-label">Carburant</span>
            <strong>{data.fuel_purchase_today ? "Signalé" : "Non signalé"}</strong>
          </article>
        </div>

        <div className="button-row">
          <Link className="button button-primary" to="/manager/lavage/ajouter/">
            Ajouter un lavage
          </Link>
          <Link className="button button-muted" to="/manager/eau/">
            Signaler eau
          </Link>
          <Link className="button button-muted" to="/manager/carburant/">
            Signaler carburant
          </Link>
        </div>

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Montant total déclaré (FC)</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={declaredAmount}
              onChange={(event) => setDeclaredAmount(event.target.value)}
              disabled={data.report_submitted || busy}
              required
            />
          </label>

          <div className="field field-full">
            <span>Dépenses connues</span>
            <div className="expense-stack">
              {knownExpenses.map((expense, index) => (
                <label key={expense.key} className="expense-known-row">
                  <input
                    type="checkbox"
                    checked={expense.selected}
                    disabled={data.report_submitted || busy}
                    onChange={(event) => updateKnownExpense(index, "selected", event.target.checked)}
                  />
                  <span>{expense.label}</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={expense.amount_value}
                    disabled={data.report_submitted || busy}
                    onChange={(event) => updateKnownExpense(index, "amount_value", event.target.value)}
                  />
                </label>
              ))}
            </div>
          </div>

          <div className="field field-full">
            <span>Dépenses supplémentaires</span>
            <div className="expense-stack">
              {customExpenses.map((expense, index) => (
                <CustomExpenseRow
                  key={expense.clientId}
                  value={expense}
                  index={index}
                  onChange={updateCustomExpense}
                  onRemove={removeCustomExpense}
                  disabled={data.report_submitted || busy}
                />
              ))}
              <button
                type="button"
                className="button button-muted"
                disabled={data.report_submitted || busy}
                onClick={() => setCustomExpenses((currentExpenses) => [...currentExpenses, createCustomExpense()])}
              >
                Ajouter une ligne
              </button>
            </div>
          </div>

          <div className="field field-full">
            <span>Photos des équipements en fin de journée</span>
            {equipmentChecklist.length ? (
              <div className="equipment-check-grid">
                {equipmentChecklist.map((machine) => {
                  const pendingPhotos = equipmentPhotos[machine.id] || [];
                  const submittedPhotos = machine.submitted_photos || [];
                  return (
                    <article key={machine.id} className="equipment-check-card">
                      <div className="equipment-check-head">
                        <div>
                          <h3>{machine.name}</h3>
                          <p>{data.report_submitted ? `${machine.submitted_photo_count} photo(s) envoyée(s)` : "Photo obligatoire avant l'envoi"}</p>
                        </div>
                        <strong>{data.report_submitted || pendingPhotos.length ? "OK" : "À faire"}</strong>
                      </div>
                      <input
                        id={`equipment-photo-${machine.id}`}
                        type="file"
                        accept="image/*"
                        capture="environment"
                        multiple
                        hidden
                        disabled={data.report_submitted || busy}
                        onChange={(event) => {
                          addEquipmentPhotos(machine.id, event.target.files);
                          event.target.value = "";
                        }}
                      />
                      {!data.report_submitted ? (
                        <button
                          type="button"
                          className="button button-muted"
                          disabled={busy}
                          onClick={() => document.getElementById(`equipment-photo-${machine.id}`)?.click()}
                        >
                          Prendre photo
                        </button>
                      ) : null}
                      {pendingPhotos.length ? (
                        <div className="capture-preview-grid">
                          {pendingPhotos.map((photo) => (
                            <article key={photo.id} className="capture-preview-card">
                              <button
                                type="button"
                                className="capture-remove"
                                onClick={() => removeEquipmentPhoto(machine.id, photo.id)}
                                disabled={busy}
                                aria-label="Supprimer la photo"
                              >
                                ×
                              </button>
                              <img src={photo.previewUrl} alt={machine.name} className="capture-preview-image" />
                              <div className="capture-preview-label">{machine.name}</div>
                            </article>
                          ))}
                        </div>
                      ) : null}
                      {submittedPhotos.length ? (
                        <div className="capture-preview-grid">
                          {submittedPhotos.map((photo) => (
                            <article key={photo.id} className="capture-preview-card">
                              <img src={photo.photo_url} alt={photo.machine_name} className="capture-preview-image" />
                              <div className="capture-preview-label">{photo.machine_name}</div>
                            </article>
                          ))}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </div>
            ) : (
              <p className="inline-muted">Aucun équipement actif n'est configuré dans le Manuel du Manager.</p>
            )}
          </div>

          <label className="field field-full">
            <span>Notes opérationnelles</span>
            <textarea
              rows="5"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              disabled={data.report_submitted || busy}
              placeholder="Présence, incidents, remarques clients ou matériel..."
            />
          </label>
          {previewOpen ? (
            <div className="field-full preview-panel">
              <p className="eyebrow">Aperçu avant envoi</p>
              <h2>Vérifier le rapport final</h2>
              <div className="preview-grid">
                <div><strong>Site</strong><span>{data.site.nom}</span></div>
                <div><strong>Date</strong><span>{data.date}</span></div>
                <div><strong>Lavages</strong><span>{data.total_lavages}</span></div>
                <div><strong>Présents</strong><span>{data.attendance_count}</span></div>
                <div><strong>Montant déclaré</strong><span>{declaredAmount || "0"} FC</span></div>
                <div><strong>Problèmes</strong><span>{data.issue_count}</span></div>
              </div>
              <div className="preview-list">
                <strong>Dépenses</strong>
                {expensePreviewRows.length ? (
                  expensePreviewRows.map((expense, index) => (
                    <span key={`${expense.label}-${index}`}>{expense.label}: {expense.amount} FC</span>
                  ))
                ) : (
                  <span>Aucune dépense déclarée.</span>
                )}
              </div>
              <div className="preview-list">
                <strong>Photos équipements</strong>
                {equipmentChecklist.length ? (
                  equipmentChecklist.map((machine) => (
                    <span key={machine.id}>
                      {machine.name}: {(equipmentPhotos[machine.id] || []).length} photo(s)
                    </span>
                  ))
                ) : (
                  <span>Aucun équipement actif configuré.</span>
                )}
                {missingMachines.length ? (
                  <span>À compléter: {missingMachines.map((machine) => machine.name).join(", ")}</span>
                ) : null}
              </div>
              {notes ? <p className="inline-muted">Notes: {notes}</p> : null}
              <div className="button-row">
                <button type="button" className="button button-primary" onClick={confirmSubmit} disabled={busy}>
                  {busy ? "Envoi..." : "Confirmer et envoyer une seule fois"}
                </button>
                <button type="button" className="button button-muted" onClick={() => setPreviewOpen(false)} disabled={busy}>
                  Modifier
                </button>
              </div>
            </div>
          ) : null}
          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy || data.report_submitted}>
              {data.report_submitted ? "Rapport déjà envoyé" : busy ? "Envoi..." : "Voir l'aperçu avant envoi"}
            </button>
          </div>
        </form>
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Présences du jour</p>
            <h2>Arrivées et clôtures</h2>
          </div>
          <Link className="button button-muted" to="/manager/presence/">
            Ma présence
          </Link>
        </div>
        {data.attendance_rows.length ? (
          <div className="list-stack">
            {data.attendance_rows.map((attendance) => (
              <article key={attendance.id} className="list-card compact-card">
                <div className="list-content">
                  <h3>{attendance.employee_name}</h3>
                  <p>{attendance.role_label}</p>
                  <p>Arrivée: {attendance.clock_in_display}</p>
                  <p>Fin: {attendance.clock_out_display || "Non clôturée"}</p>
                  <p>{attendance.status_label}</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="Aucune présence"
            description="Aucun employé n'a encore pointé son arrivée pour cette journée."
          />
        )}
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Lavages du jour</p>
            <h2>Photos et voitures enregistrées</h2>
          </div>
          <Link className="button button-primary" to="/manager/lavage/ajouter/">
            Nouveau lavage
          </Link>
        </div>
        {data.today_washes.length ? (
          <div className="list-stack">
            {data.today_washes_truncated ? (
              <p className="inline-muted">
                Affichage des {data.today_washes.length} derniers lavages. La liste complète reste disponible dans la section Lavages.
              </p>
            ) : null}
            {data.today_washes.map((wash) => (
              <article key={wash.id} className="list-card compact-card">
                <div className="list-content">
                  <h3>{wash.type_service_display}</h3>
                  <p>{wash.employee_name}</p>
                  <p>{wash.date_display}</p>
                  <p>{wash.photo_count} photo(s)</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Aucun lavage" description="Aucun lavage n'a encore été enregistré aujourd'hui." />
        )}
      </section>

      <section className="section-card">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Problèmes du jour</p>
            <h2>Signalements</h2>
          </div>
          <Link className="button button-muted" to="/manager/probleme/signaler/">
            Signaler
          </Link>
        </div>
        {data.today_issues.length ? (
          <div className="list-stack">
            {data.today_issues_truncated ? (
              <p className="inline-muted">
                Affichage des {data.today_issues.length} derniers problèmes. La liste complète reste disponible dans la section Problèmes.
              </p>
            ) : null}
            {data.today_issues.map((issue) => (
              <article key={issue.id} className="list-card compact-card">
                <div className="list-content">
                  <h3>{issue.categorie_display}</h3>
                  <p>{issue.employee_name}</p>
                  <p>{issue.statut_display}</p>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState title="Aucun problème" description="Aucun problème n'a été signalé aujourd'hui." />
        )}
      </section>
    </div>
  );
}
