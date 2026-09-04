import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

type Dict = Record<string, string>;

interface IntlContextValue {
  lang: string;
  t: (key: string) => string;
}

const IntlContext = createContext<IntlContextValue>({
  lang: "en",
  t: (key) => key,
});

function resolveLang(): string {
  if (typeof window === "undefined") return "en";
  const fromQuery = new URLSearchParams(window.location.search).get("lang");
  if (fromQuery) return fromQuery.toLowerCase();
  const nav = window.navigator?.language;
  if (nav) return nav.split("-")[0].toLowerCase();
  return "en";
}


export function IntlProvider({ children }: { children: ReactNode }) {
  const [lang] = useState(resolveLang);
  const [dict, setDict] = useState<Dict>({});

  useEffect(() => {
    if (lang === "en") return;
    let cancelled = false;
    fetch(`/api/i18n/${lang}.json`)
      .then((r) => (r.ok ? r.json() : {}))
      .then((d: Dict) => {
        if (!cancelled) setDict(d);
      })
      .catch(() => {
        // missing/failed locale — fall back to source strings
      });
    return () => {
      cancelled = true;
    };
  }, [lang]);

  const value = useMemo<IntlContextValue>(
    () => ({
      lang,
      t: (key: string) => dict[key] ?? key,
    }),
    [dict, lang],
  );
  return <IntlContext.Provider value={value}>{children}</IntlContext.Provider>;
}

export function useT(): (key: string) => string {
  return useContext(IntlContext).t;
}

export function useLang(): string {
  return useContext(IntlContext).lang;
}
