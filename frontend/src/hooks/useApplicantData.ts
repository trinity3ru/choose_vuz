// Хук загрузки заявлений по выбранному вузу и направлению.

import { useEffect, useState } from "react";

import { fetchApplicants } from "../api";
import type { ApplicantsResponse } from "../types";

interface State {
  data: ApplicantsResponse | null;
  loading: boolean;
  error: string | null;
}

export function useApplicantData(
  universityCode: string | null,
  majorCode: string | null,
): State {
  const [state, setState] = useState<State>({
    data: null,
    loading: false,
    error: null,
  });

  useEffect(() => {
    if (!universityCode || !majorCode) {
      setState({ data: null, loading: false, error: null });
      return;
    }

    let cancelled = false;
    setState({ data: null, loading: true, error: null });

    fetchApplicants(universityCode, majorCode)
      .then((data) => {
        if (!cancelled) setState({ data, loading: false, error: null });
      })
      .catch((err: Error) => {
        if (!cancelled)
          setState({ data: null, loading: false, error: err.message });
      });

    return () => {
      cancelled = true;
    };
  }, [universityCode, majorCode]);

  return state;
}
