// Хук загрузки заявлений по выбранному вузу и направлению.

import { useCallback, useEffect, useState } from "react";

import { ApiUnavailableError, fetchApplicants } from "../api";
import type { ApplicantsResponse } from "../types";

interface State {
  data: ApplicantsResponse | null;
  loading: boolean;
  error: string | null;
  /** true — API не отвечает (сеть/5xx): показываем экран с «Повторить». */
  unavailable: boolean;
}

export function useApplicantData(
  universityCode: string | null,
  majorCode: string | null,
): State & { retry: () => void } {
  const [state, setState] = useState<State>({
    data: null,
    loading: false,
    error: null,
    unavailable: false,
  });
  // Счётчик попыток: retry() перезапускает эффект с теми же кодами.
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  useEffect(() => {
    if (!universityCode || !majorCode) {
      setState({ data: null, loading: false, error: null, unavailable: false });
      return;
    }

    let cancelled = false;
    setState({ data: null, loading: true, error: null, unavailable: false });

    fetchApplicants(universityCode, majorCode)
      .then((data) => {
        if (!cancelled)
          setState({ data, loading: false, error: null, unavailable: false });
      })
      .catch((err: Error) => {
        if (!cancelled)
          setState({
            data: null,
            loading: false,
            error: err.message,
            unavailable: err instanceof ApiUnavailableError,
          });
      });

    return () => {
      cancelled = true;
    };
  }, [universityCode, majorCode, attempt]);

  return { ...state, retry };
}
