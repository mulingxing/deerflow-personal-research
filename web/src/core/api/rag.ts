import type { Resource } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export type RAGUploadStatus = "queued" | "processing" | "completed" | "failed";

export interface RAGUploadJob {
  task_id: string;
  status: RAGUploadStatus;
  progress: number;
  filename: string;
  resource?: Resource | null;
  error?: string | null;
}

async function readAPIError(response: Response): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return new Error(payload.detail ?? `HTTP ${response.status}`);
  } catch {
    return new Error(`HTTP ${response.status}`);
  }
}

export async function listRAGResources(query = ""): Promise<Resource[]> {
  const url = new URL(resolveServiceURL("rag/resources"));
  if (query) url.searchParams.set("query", query);

  const response = await fetch(url, { method: "GET" });
  if (!response.ok) throw await readAPIError(response);

  const result = (await response.json()) as { resources?: Resource[] };
  return result.resources ?? [];
}

export async function queryRAGResources(query: string): Promise<Resource[]> {
  try {
    return await listRAGResources(query);
  } catch {
    return [];
  }
}

export async function startRAGUpload(file: File): Promise<RAGUploadJob> {
  const body = new FormData();
  body.append("file", file);

  const response = await fetch(resolveServiceURL("rag/upload/jobs"), {
    method: "POST",
    body,
  });
  if (!response.ok) throw await readAPIError(response);

  return (await response.json()) as RAGUploadJob;
}

export async function getRAGUploadJob(taskId: string): Promise<RAGUploadJob> {
  const response = await fetch(
    resolveServiceURL(`rag/upload/jobs/${encodeURIComponent(taskId)}`),
    { method: "GET" },
  );
  if (!response.ok) throw await readAPIError(response);

  return (await response.json()) as RAGUploadJob;
}
