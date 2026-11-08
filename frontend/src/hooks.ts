import { useEffect, useState } from "react";

/** Telefon düzeni: alt sekme çubuğu, kart listeleri. */
export const MOBILE_QUERY = "(max-width: 760px)";

export function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

export const useIsMobile = () => useMedia(MOBILE_QUERY);
