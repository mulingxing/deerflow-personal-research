import type { Citation, Message, Resource } from "../messages";

import { resolveServiceURL } from "./resolve-service-url";

export type ConversationStatus =
  | "idle"
  | "running"
  | "waiting_feedback"
  | "needs_retry";

export type ResearchMode = "web" | "local" | "hybrid";

export interface ConversationSnapshot {
  version: 1;
  messageIds: string[];
  messages: Array<[string, Message]>;
  researchIds: string[];
  researchPlanIds: Array<[string, string]>;
  researchReportIds: Array<[string, string]>;
  researchActivityIds: Array<[string, string[]]>;
  researchQueries: Array<[string, string]>;
  researchCitations: Array<[string, Citation[]]>;
  openResearchId: string | null;
  activeRunThreadId: string | null;
  selectedResources: Resource[];
  researchMode: ResearchMode;
}

export interface ConversationSummary {
  id: string;
  title: string;
  status: ConversationStatus;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  snapshot: ConversationSnapshot;
}

async function readResponseError(response: Response): Promise<Error> {
  try {
    const data = (await response.json()) as { detail?: string };
    return new Error(data.detail ?? `HTTP ${response.status}`);
  } catch {
    return new Error(`HTTP ${response.status}`);
  }
}

export async function listConversations(): Promise<ConversationSummary[]> {
  const conversations: ConversationSummary[] = [];
  while (true) {
    const url = new URL(resolveServiceURL("conversations"));
    url.searchParams.set("limit", "100");
    url.searchParams.set("offset", String(conversations.length));
    const response = await fetch(url);
    if (!response.ok) throw await readResponseError(response);
    const result = (await response.json()) as {
      conversations: ConversationSummary[];
    };
    conversations.push(...result.conversations);
    if (result.conversations.length < 100) return conversations;
  }
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  const response = await fetch(
    resolveServiceURL(`conversations/${encodeURIComponent(id)}`),
  );
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ConversationDetail;
}

export async function saveConversation(
  id: string,
  title: string,
  status: ConversationStatus,
  snapshot: ConversationSnapshot,
  expectedUpdatedAt: string | null,
): Promise<ConversationDetail> {
  const response = await fetch(
    resolveServiceURL(`conversations/${encodeURIComponent(id)}`),
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        status,
        snapshot,
        expected_updated_at: expectedUpdatedAt,
      }),
    },
  );
  if (!response.ok) throw await readResponseError(response);
  return (await response.json()) as ConversationDetail;
}

export async function deleteConversation(
  id: string,
  expectedUpdatedAt?: string,
): Promise<void> {
  const url = new URL(
    resolveServiceURL(`conversations/${encodeURIComponent(id)}`),
  );
  if (expectedUpdatedAt) {
    url.searchParams.set("expected_updated_at", expectedUpdatedAt);
  }
  const response = await fetch(url, { method: "DELETE" });
  if (!response.ok) throw await readResponseError(response);
}
