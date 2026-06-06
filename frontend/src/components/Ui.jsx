import React from "react";

export function Notice({ type = "info", children, onDismiss }) {
  return (
    <div className={`notice notice-${type}`}>
      <div>{children}</div>
      {onDismiss ? (
        <button type="button" className="notice-close" onClick={onDismiss}>
          Fermer
        </button>
      ) : null}
    </div>
  );
}

export function LoadingState({ label = "Chargement..." }) {
  return (
    <div className="state-card">
      <div className="spinner" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="state-card state-card-error">
      <h3>Impossible de charger cette page</h3>
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="button button-primary" onClick={onRetry}>
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, description }) {
  return (
    <div className="state-card">
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  );
}

export function Pagination({ pageData, onPageChange }) {
  if (!pageData || pageData.num_pages <= 1) {
    return null;
  }

  const pages = [];
  for (let page = 1; page <= pageData.num_pages; page += 1) {
    pages.push(page);
  }

  return (
    <div className="pagination">
      <button
        type="button"
        className="button button-muted"
        disabled={!pageData.has_previous}
        onClick={() => onPageChange(pageData.page - 1)}
      >
        Précédent
      </button>
      <div className="pagination-pages">
        {pages.map((page) => (
          <button
            key={page}
            type="button"
            className={`pagination-page ${page === pageData.page ? "is-active" : ""}`}
            onClick={() => onPageChange(page)}
          >
            {page}
          </button>
        ))}
      </div>
      <button
        type="button"
        className="button button-muted"
        disabled={!pageData.has_next}
        onClick={() => onPageChange(pageData.page + 1)}
      >
        Suivant
      </button>
    </div>
  );
}

export function ImageThumb({ src, alt, large = false }) {
  if (!src) {
    return <div className={`image-placeholder ${large ? "image-placeholder-large" : ""}`}>Aucune image</div>;
  }

  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      decoding="async"
      className={large ? "image-thumb image-thumb-large" : "image-thumb"}
    />
  );
}
