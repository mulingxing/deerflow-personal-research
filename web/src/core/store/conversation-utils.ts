import type {
  ConversationSnapshot,
  ConversationStatus,
  ResearchMode,
} from "../api/history";
import type { Citation, Message, Resource } from "../messages";

export interface ConversationStateData {
  messageIds: string[];
  messages: Map<string, Message>;
  researchIds: string[];
  researchPlanIds: Map<string, string>;
  researchReportIds: Map<string, string>;
  researchActivityIds: Map<string, string[]>;
  researchQueries: Map<string, string>;
  researchCitations: Map<string, Citation[]>;
  openResearchId: string | null;
  activeRunThreadId: string | null;
  selectedResources: Resource[];
  researchMode: ResearchMode;
}

function isFinishedAssistant(message: Message): boolean {
  return (
    message.finishReason === "stop" ||
    (message.agent === "coordinator" &&
      message.finishReason === "tool_calls" &&
      Boolean(
        message.toolCalls?.some((call) => call.name === "direct_response"),
      ))
  );
}

export function resolveResearchSelection(
  mode: ResearchMode,
  savedResources: Resource[],
  requestedResources?: Resource[],
): { valid: boolean; resources: Resource[]; enableWebSearch: boolean } {
  const resources =
    mode === "web" ? [] : (requestedResources ?? savedResources);
  return {
    valid: mode === "web" || resources.length > 0,
    resources,
    enableWebSearch: mode !== "local",
  };
}

export function completedRunStatus(
  messages: Map<string, Message>,
  runThreadId: string,
  hadError: boolean,
  sawInterrupt: boolean,
): ConversationStatus {
  if (hadError) return "needs_retry";
  if (sawInterrupt) return "waiting_feedback";

  const runMessages = [...messages.values()].filter(
    (message) => message.threadId === runThreadId,
  );
  if (runMessages.some((message) => message.isStreaming)) return "needs_retry";

  const hasAnswer = runMessages.some(
    (message) =>
      (message.agent === "reporter" && message.finishReason === "stop") ||
      (message.agent === "coordinator" &&
        message.finishReason === "tool_calls" &&
        message.toolCalls?.some((call) => call.name === "direct_response")),
  );
  return hasAnswer ? "idle" : "needs_retry";
}

export function makeConversationSnapshot(
  state: ConversationStateData,
): ConversationSnapshot {
  return {
    version: 1,
    messageIds: [...state.messageIds],
    messages: [...state.messages],
    researchIds: [...state.researchIds],
    researchPlanIds: [...state.researchPlanIds],
    researchReportIds: [...state.researchReportIds],
    researchActivityIds: [...state.researchActivityIds],
    researchQueries: [...state.researchQueries],
    researchCitations: [...state.researchCitations],
    openResearchId: state.openResearchId,
    activeRunThreadId: state.activeRunThreadId,
    selectedResources: [...state.selectedResources],
    researchMode: state.researchMode,
  };
}

export function restoreConversationSnapshot(
  snapshot: ConversationSnapshot,
  interrupted = false,
): ConversationStateData {
  // 历史记录可能来自旧版本，缺失的字段按空会话处理。
  const messages = new Map(snapshot.messages ?? []);
  if (interrupted) {
    for (const [id, message] of messages) {
      if (
        message.isStreaming ||
        (message.threadId === snapshot.activeRunThreadId &&
          message.role === "assistant" &&
          !isFinishedAssistant(message))
      ) {
        // 中断的文字保留给用户查看，但不能继续显示无限加载动画。
        messages.set(id, {
          ...message,
          isStreaming: false,
          historyIncomplete: true,
        });
      }
    }
  }
  return {
    messageIds: snapshot.messageIds ?? [],
    messages,
    researchIds: snapshot.researchIds ?? [],
    researchPlanIds: new Map(snapshot.researchPlanIds ?? []),
    researchReportIds: new Map(snapshot.researchReportIds ?? []),
    researchActivityIds: new Map(snapshot.researchActivityIds ?? []),
    researchQueries: new Map(snapshot.researchQueries ?? []),
    researchCitations: new Map(snapshot.researchCitations ?? []),
    openResearchId: snapshot.openResearchId ?? null,
    activeRunThreadId: snapshot.activeRunThreadId ?? null,
    selectedResources: snapshot.selectedResources ?? [],
    researchMode: snapshot.researchMode ?? "web",
  };
}

export function conversationTitle(state: ConversationStateData): string {
  const firstQuestion = state.messageIds
    .map((id) => state.messages.get(id))
    .find((message) => message?.role === "user" && !message.interruptFeedback);
  const title = firstQuestion?.content.replace(/\s+/g, " ").trim().slice(0, 60);
  return title?.length ? title : "新对话";
}

export function boundedConversationHistory(
  state: Pick<ConversationStateData, "messageIds" | "messages">,
): Array<{ role: "user" | "assistant"; content: string }> {
  const candidates = state.messageIds
    .map((id) => state.messages.get(id))
    .filter((message): message is Message => Boolean(message))
    .filter(
      (message) =>
        Boolean(message.content.trim()) &&
        !message.isStreaming &&
        !message.historyIncomplete &&
        ((message.role === "user" && !message.interruptFeedback) ||
          (message.role === "assistant" &&
            (message.agent === "reporter" || message.agent === "coordinator") &&
            isFinishedAssistant(message))),
    );

  const result: Array<{ role: "user" | "assistant"; content: string }> = [];
  let totalChars = 0;
  for (const message of candidates.slice(-12).reverse()) {
    const content = message.content.trim().slice(0, 3000);
    if (totalChars + content.length > 12000) break;
    result.unshift({ role: message.role as "user" | "assistant", content });
    totalChars += content.length;
  }
  return result;
}
