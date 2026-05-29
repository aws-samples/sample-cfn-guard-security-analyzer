/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** REST API base URL, e.g. https://<id>.execute-api.<region>.amazonaws.com/<stage> */
  readonly VITE_API_URL?: string;
  /** WebSocket API URL, e.g. wss://<id>.execute-api.<region>.amazonaws.com/<stage> */
  readonly VITE_WS_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
