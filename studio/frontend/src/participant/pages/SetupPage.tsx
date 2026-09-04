import { useEffect, useState } from "react";
import { apiGet } from "../../lib/api";
import "../../styles/setup.css";

export function SetupPage() {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    apiGet<{ html: string }>("/api/setup").then((res) => setHtml(res.html));
  }, []);

  if (!html) return null;
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
