import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { apiGet } from "../../lib/api";
import type { NextResponse } from "../../lib/types";

export function ResumePage() {
  const navigate = useNavigate();

  useEffect(() => {
    apiGet<NextResponse>("/api/p/resume").then((res) => {
      navigate(res.next ?? "/", { replace: true });
    });
  }, [navigate]);

  return null;
}
