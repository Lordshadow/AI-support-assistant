import React from 'react';

export const Toast = ({ toast, onClose }) => {
  if (!toast) return null;

  const isError = toast.type === 'error';

  return (
    <div className={`toast-container ${isError ? 'toast-error' : 'toast-success'}`}>
      <span className="toast-icon">{isError ? '⚠️' : '✅'}</span>
      <div className="toast-message">{toast.message}</div>
      <button onClick={onClose} className="toast-close">
        &times;
      </button>
    </div>
  );
};
