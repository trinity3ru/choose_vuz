/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Базовый URL API (prod: https://api.vuzfinder.ru; в dev пусто — Vite-прокси). */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
