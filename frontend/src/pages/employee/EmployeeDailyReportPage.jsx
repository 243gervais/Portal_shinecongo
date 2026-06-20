import React, { useEffect, useRef, useState } from "react";

import { apiFetch } from "../../lib/api";
import { ErrorState, LoadingState, Notice } from "../../components/Ui";

function CustomExpenseRow({ value, index, onChange, onRemove }) {
  return (
    <div className="expense-row">
      <input
        type="text"
        value={value.label}
        placeholder="Nom de la dépense"
        onChange={(event) => onChange(index, "label", event.target.value)}
      />
      <input
        type="number"
        value={value.amount_value}
        placeholder="Montant FC"
        min="0"
        step="0.01"
        onChange={(event) => onChange(index, "amount_value", event.target.value)}
      />
      <button type="button" className="button button-muted" onClick={() => onRemove(index)}>
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

export default function EmployeeDailyReportPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [knownExpenses, setKnownExpenses] = useState([]);
  const [customExpenses, setCustomExpenses] = useState([]);
  const [declaredAmount, setDeclaredAmount] = useState("");
  const customExpenseIdRef = useRef(0);

  function createCustomExpense(expense = {}) {
    const clientId = `custom-expense-${customExpenseIdRef.current}`;
    customExpenseIdRef.current += 1;
    return normalizeCustomExpense(expense, clientId);
  }

  async function load() {
    try {
      setError("");
      const payload = await apiFetch("/employee/rapport-journalier/");
      setData(payload);
      setKnownExpenses(payload.expense_form.known || []);
      setCustomExpenses((payload.expense_form.custom || []).map((expense) => createCustomExpense(expense)));
      setDeclaredAmount(payload.submitted_total_amount || "");
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  useEffect(() => {
    load();
  }, []);

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

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setNotice("");

    try {
      const formData = new FormData();
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

      const payload = await apiFetch("/employee/rapport-journalier/", {
        method: "POST",
        data: formData,
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
    return <LoadingState label="Chargement du rapport..." />;
  }

  return (
    <div className="page-stack">
      <section className="section-card">
        <p className="eyebrow">Rapport du jour</p>
        <h1>{data.site.nom}</h1>
        <p>{data.computed_total_washes} lavage(s) enregistrés aujourd&apos;hui.</p>
        {notice ? <Notice type="info">{notice}</Notice> : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Montant total déclaré (FC)</span>
            <input
              type="number"
              min="0"
              step="0.01"
              value={declaredAmount}
              onChange={(event) => setDeclaredAmount(event.target.value)}
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
                    onChange={(event) => updateKnownExpense(index, "selected", event.target.checked)}
                  />
                  <span>{expense.label}</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={expense.amount_value}
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
                />
              ))}
              <button
                type="button"
                className="button button-muted"
                onClick={() => setCustomExpenses((currentExpenses) => [...currentExpenses, createCustomExpense()])}
              >
                Ajouter une ligne
              </button>
            </div>
          </div>

          <div className="field-full form-actions">
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? "Enregistrement..." : "Enregistrer le rapport"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
