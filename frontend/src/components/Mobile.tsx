import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

const PATHS: Record<string, ReactNode> = {
  weekly: <><rect x="3.5" y="5" width="17" height="15" rx="2.5" /><path d="M3.5 10h17M8 3v4M16 3v4" /></>,
  sitstart: <><rect x="2.5" y="7" width="19" height="10" rx="5" /><circle cx="16.5" cy="12" r="2.6" /></>,
  fa: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6.2 6.5-6.2s6.5 2.6 6.5 6.2M18.5 8v6M15.5 11h6" /></>,
  news: <><path d="M4 5h13v14H6.5A2.5 2.5 0 0 1 4 16.5V5z" /><path d="M17 9h3v8.5a1.5 1.5 0 0 1-3 0M7.5 9h6M7.5 12.5h6M7.5 16h3.5" /></>,
  more: <><circle cx="5" cy="12" r="1.4" fill="currentColor" /><circle cx="12" cy="12" r="1.4" fill="currentColor" /><circle cx="19" cy="12" r="1.4" fill="currentColor" /></>,
  sync: <><path d="M20 12a8 8 0 1 1-2.35-5.65" /><path d="M20 4v5h-5" /></>,
  trade: <path d="M4 8h15M15 4l4 4-4 4M20 16H5M9 12l-4 4 4 4" />,
  suggest: <path d="M9.5 18h5M10.5 21h3M12 3a6 6 0 0 0-3.6 10.8c.7.5 1.1 1.3 1.1 2.2h5c0-.9.4-1.7 1.1-2.2A6 6 0 0 0 12 3z" />,
  multi: <><circle cx="6" cy="6" r="2.5" /><circle cx="18" cy="6" r="2.5" /><circle cx="12" cy="18" r="2.5" /><path d="M8.5 6h7M7.2 8.3l3.6 7.4M16.8 8.3l-3.6 7.4" /></>,
  history: <path d="M3 20h18M6.5 17v-5M11.5 17V6M16.5 17V9.5" />,
  season: <path d="M8 4h8v5a4 4 0 0 1-8 0V4zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8.5 20h7M10 17h4" />,
  ranks: <path d="M10 6h10M10 12h10M10 18h10M4.5 6h1M4.5 12h1M4.5 18h1" />,
  chevron: <path d="M7 10l5 5 5-5" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}

/** Alttan açılan panel (telefon): arka plana dokununca ya da Esc ile kapanır. */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") close.current(); };
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
    };
  }, []);
  return createPortal(
    <>
      <div className="sheet-bg" onClick={onClose} />
      <div className="sheet" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={panel}>
        <div className="sheet-handle" />
        <div className="sheet-h">
          <h2>{title}</h2>
          <button className="m-icon" aria-label="Kapat" onClick={onClose}><Icon name="close" size={18} /></button>
        </div>
        {children}
      </div>
    </>,
    document.body,
  );
}
