// Хук состояния парсеров (/api/v1/parser/health): свежесть данных по вузам.
//
// Ошибки загрузки health некритичны для дашборда: бейдж свежести просто
// не показывается (основной поток данных обрабатывает недоступность сам).

import { useCallback, useEffect, useState } from "react";

import { fetchParserHealth } from "../api";
import type { ParserHealthUniversity } from "../types";

interface State {
  /** Состояние по коду вуза (SPBSTU, ITMO, ...). */
  byCode: Map<string, ParserHealthUniversity>;
  loaded: boolean;
}

export function useParserHealth(): State & { reload: () => void } {
  const [state, setState] = useState<State>({ byCode: new Map(), loaded: false });

  const load = useCallback(() => {
    fetchParserHealth()
      .then((report) => {
        const byCode = new Map(report.universities.map((u) => [u.code, u]));
        setState({ byCode, loaded: true });
      })
      .catch(() => {
        setState({ byCode: new Map(), loaded: false });
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { ...state, reload: load };
}
