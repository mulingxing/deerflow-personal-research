// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { nanoid } from "nanoid";
import { toast } from "sonner";
import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";

import { env } from "~/env";

import { chatStream, generatePodcast } from "../api";
import {
  deleteConversation as deleteConversationAPI,
  getConversation,
  listConversations,
  saveConversation as saveConversationAPI,
  type ConversationSnapshot,
  type ConversationStatus,
  type ConversationSummary,
  type ResearchMode,
} from "../api/history";
import type { Citation, Message, Resource } from "../messages";
import { mergeMessage } from "../messages";
import { parseJSON } from "../utils";

import {
  boundedConversationHistory,
  completedRunStatus,
  conversationTitle,
  makeConversationSnapshot,
  resolveResearchSelection,
  restoreConversationSnapshot,
} from "./conversation-utils";
import { getChatStreamSettings, setEnableWebSearch } from "./settings-store";

const ACTIVE_CONVERSATION_KEY = "deerflow.active-conversation";
const ACTIVE_RUN_OWNER_KEY = "deerflow.active-run-owner";
const initialConversationId = nanoid();

function readBrowserStorage(
  scope: "local" | "session",
  key: string,
): string | null {
  try {
    return (
      scope === "local" ? window.localStorage : window.sessionStorage
    ).getItem(key);
  } catch {
    return null;
  }
}

function writeBrowserStorage(
  scope: "local" | "session",
  key: string,
  value: string,
): void {
  try {
    (scope === "local" ? window.localStorage : window.sessionStorage).setItem(
      key,
      value,
    );
  } catch {
    // 浏览器禁用 Web Storage 时，当前页面和后端历史功能仍可继续使用。
  }
}

function removeBrowserStorage(scope: "local" | "session", key: string): void {
  try {
    (scope === "local"
      ? window.localStorage
      : window.sessionStorage
    ).removeItem(key);
  } catch {
    // 无法访问存储时无需清理；运行状态仍由内存和服务端记录决定。
  }
}

export const useStore = create<{
  responding: boolean;
  sendStarting: boolean;
  conversationSwitching: boolean;
  remoteRunning: boolean;
  conversationId: string;
  conversationStatus: ConversationStatus;
  conversations: ConversationSummary[];
  historyLoading: boolean;
  historyError: string | null;
  activeRunThreadId: string | null;
  selectedResources: Resource[];
  researchMode: ResearchMode;
  threadId: string | undefined;
  messageIds: string[];
  messages: Map<string, Message>;
  researchIds: string[];
  researchPlanIds: Map<string, string>;
  researchReportIds: Map<string, string>;
  researchActivityIds: Map<string, string[]>;
  researchQueries: Map<string, string>;
  researchCitations: Map<string, Citation[]>;
  ongoingResearchId: string | null;
  openResearchId: string | null;

  appendMessage: (message: Message) => void;
  updateMessage: (message: Message) => void;
  updateMessages: (messages: Message[]) => void;
  openResearch: (researchId: string | null) => void;
  closeResearch: () => void;
  setOngoingResearch: (researchId: string | null) => void;
  setCitations: (researchId: string, citations: Citation[]) => void;
  setSelectedResources: (
    value: Resource[] | ((current: Resource[]) => Resource[]),
  ) => void;
  setResearchMode: (mode: ResearchMode) => void;
}>((set) => ({
  responding: false,
  sendStarting: false,
  conversationSwitching: false,
  remoteRunning: false,
  conversationId: initialConversationId,
  conversationStatus: "idle",
  conversations: [],
  historyLoading: true,
  historyError: null,
  activeRunThreadId: null,
  selectedResources: [],
  researchMode: getChatStreamSettings().enableWebSearch ? "web" : "local",
  threadId: undefined,
  messageIds: [],
  messages: new Map<string, Message>(),
  researchIds: [],
  researchPlanIds: new Map<string, string>(),
  researchReportIds: new Map<string, string>(),
  researchActivityIds: new Map<string, string[]>(),
  researchQueries: new Map<string, string>(),
  researchCitations: new Map<string, Citation[]>(),
  ongoingResearchId: null,
  openResearchId: null,

  appendMessage(message: Message) {
    set((state) => {
      // Prevent duplicate message IDs in the array to avoid React key warnings
      const newMessageIds = state.messageIds.includes(message.id)
        ? state.messageIds
        : [...state.messageIds, message.id];
      return {
        messageIds: newMessageIds,
        messages: new Map(state.messages).set(message.id, message),
      };
    });
  },
  updateMessage(message: Message) {
    set((state) => ({
      messages: new Map(state.messages).set(message.id, message),
    }));
  },
  updateMessages(messages: Message[]) {
    set((state) => {
      const newMessages = new Map(state.messages);
      messages.forEach((m) => newMessages.set(m.id, m));
      return { messages: newMessages };
    });
  },
  openResearch(researchId: string | null) {
    set({ openResearchId: researchId });
  },
  closeResearch() {
    set({ openResearchId: null });
  },
  setOngoingResearch(researchId: string | null) {
    set({ ongoingResearchId: researchId });
  },
  setCitations(researchId: string, citations: Citation[]) {
    set((state) => ({
      researchCitations: new Map(state.researchCitations).set(
        researchId,
        citations,
      ),
    }));
  },
  setSelectedResources(value) {
    set((state) => ({
      selectedResources:
        typeof value === "function" ? value(state.selectedResources) : value,
    }));
  },
  setResearchMode(researchMode) {
    set({ researchMode });
  },
}));

type ChatStoreState = ReturnType<typeof useStore.getState>;
let historyReady = false;
let historyInitialization: Promise<void> | null = null;
let saveTimer: ReturnType<typeof setTimeout> | null = null;
let saveQueue: Promise<void> = Promise.resolve();
let restoringSnapshot = false;
// 保存时带上上次读到的版本，避免多个浏览器标签页静默覆盖彼此。
const knownVersions = new Map<string, string>();

function upsertConversation(summary: ConversationSummary): void {
  useStore.setState((state) => ({
    conversations: [
      summary,
      ...state.conversations.filter((item) => item.id !== summary.id),
    ].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    historyError: null,
  }));
}

function persistConversation(state: ChatStoreState): Promise<void> {
  if (!historyReady || state.remoteRunning || state.messageIds.length === 0) {
    return Promise.resolve();
  }

  const id = state.conversationId;
  const title = conversationTitle(state);
  const status = state.conversationStatus;
  // 先序列化一份，避免后续流式更新修改同一个 Message 对象。
  const snapshot = JSON.parse(
    JSON.stringify(makeConversationSnapshot(state)),
  ) as ConversationSnapshot;

  const task = saveQueue
    .catch(() => undefined)
    .then(async () => {
      const saved = await saveConversationAPI(
        id,
        title,
        status,
        snapshot,
        knownVersions.get(id) ?? null,
      );
      knownVersions.set(id, saved.updated_at);
      upsertConversation(saved);
    });
  saveQueue = task;
  return task.catch((error: unknown) => {
    const message = error instanceof Error ? error.message : "保存会话失败";
    useStore.setState({ historyError: message });
    throw error;
  });
}

function scheduleConversationSave(): void {
  if (!historyReady || restoringSnapshot) return;
  if (saveTimer) return;
  // 流式内容持续变化时按固定间隔保存，刷新页面也能找回最近的内容。
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void persistConversation(useStore.getState()).catch((error: unknown) => {
      console.error("Failed to save conversation:", error);
    });
  }, 1500);
}

async function flushConversation(): Promise<void> {
  if (saveTimer) {
    clearTimeout(saveTimer);
    saveTimer = null;
  }
  await persistConversation(useStore.getState());
}

function emptyConversation(id: string): Partial<ChatStoreState> {
  return {
    conversationId: id,
    conversationStatus: "idle",
    remoteRunning: false,
    threadId: undefined,
    activeRunThreadId: null,
    messageIds: [],
    messages: new Map(),
    researchIds: [],
    researchPlanIds: new Map(),
    researchReportIds: new Map(),
    researchActivityIds: new Map(),
    researchQueries: new Map(),
    researchCitations: new Map(),
    ongoingResearchId: null,
    openResearchId: null,
    selectedResources: [],
    researchMode: "web",
  };
}

function restoreConversation(detail: {
  id: string;
  status: ConversationStatus;
  snapshot: ConversationSnapshot;
}): void {
  const wasRunning = detail.status === "running";
  const ownedRun =
    wasRunning &&
    readBrowserStorage("session", ACTIVE_RUN_OWNER_KEY) ===
      `${detail.id}:${detail.snapshot.activeRunThreadId}`;
  if (ownedRun) removeBrowserStorage("session", ACTIVE_RUN_OWNER_KEY);
  const restored = restoreConversationSnapshot(
    detail.snapshot,
    detail.status === "needs_retry" || wasRunning,
  );
  // 读取另一标签页的运行快照只能展示，不能把共享记录改成已中断。
  restoringSnapshot = true;
  try {
    useStore.setState({
      ...restored,
      conversationId: detail.id,
      conversationStatus: wasRunning ? "needs_retry" : detail.status,
      remoteRunning: wasRunning && !ownedRun,
      threadId: restored.activeRunThreadId ?? undefined,
      ongoingResearchId: null,
      responding: false,
    });
  } finally {
    restoringSnapshot = false;
  }
  setEnableWebSearch(restored.researchMode !== "local");
}

async function loadConversation(id: string) {
  const detail = await getConversation(id);
  knownVersions.set(id, detail.updated_at);
  return detail;
}

export function initializeConversationHistory(): Promise<void> {
  if (historyInitialization) return historyInitialization;
  historyInitialization = (async () => {
    try {
      const conversations = await listConversations();
      conversations.forEach((item) =>
        knownVersions.set(item.id, item.updated_at),
      );
      const savedId = readBrowserStorage("local", ACTIVE_CONVERSATION_KEY);
      const activeId = savedId ?? conversations[0]?.id;
      if (activeId && conversations.some((item) => item.id === activeId)) {
        const detail = await loadConversation(activeId);
        restoreConversation(detail);
        writeBrowserStorage("local", ACTIVE_CONVERSATION_KEY, activeId);
      }
      useStore.setState({
        conversations,
        historyLoading: false,
        historyError: null,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "加载会话失败";
      useStore.setState({ historyLoading: false, historyError: message });
    } finally {
      historyReady = true;
      // 只观察需要入库的字段，避免更新历史列表后再次触发保存。
      useStore.subscribe((state, previous) => {
        if (
          state.messageIds !== previous.messageIds ||
          state.messages !== previous.messages ||
          state.researchIds !== previous.researchIds ||
          state.researchPlanIds !== previous.researchPlanIds ||
          state.researchReportIds !== previous.researchReportIds ||
          state.researchActivityIds !== previous.researchActivityIds ||
          state.researchQueries !== previous.researchQueries ||
          state.researchCitations !== previous.researchCitations ||
          state.openResearchId !== previous.openResearchId ||
          state.activeRunThreadId !== previous.activeRunThreadId ||
          state.selectedResources !== previous.selectedResources ||
          state.researchMode !== previous.researchMode ||
          state.conversationStatus !== previous.conversationStatus
        ) {
          scheduleConversationSave();
        }
      });
    }
  })();
  return historyInitialization;
}

export async function refreshConversations(): Promise<void> {
  await switchConversation(async () => {
    const conversations = await listConversations();
    conversations.forEach((item) => {
      if (!knownVersions.has(item.id)) {
        knownVersions.set(item.id, item.updated_at);
      }
    });
    const current = useStore.getState();
    const active = conversations.find(
      (item) => item.id === current.conversationId,
    );
    if (current.remoteRunning && active && active.status !== "running") {
      // 另一个标签页结束后，刷新按钮也要解除本页只读状态。
      restoreConversation(await loadConversation(current.conversationId));
    }
    useStore.setState({ conversations, historyError: null });
  });
}

export async function recoverStoppedConversation(): Promise<void> {
  await switchConversation(async () => {
    const current = useStore.getState();
    if (!current.remoteRunning) return;
    const latest = await getConversation(current.conversationId);
    knownVersions.set(latest.id, latest.updated_at);
    const recovered =
      latest.status === "running"
        ? await saveConversationAPI(
            latest.id,
            latest.title,
            "needs_retry",
            latest.snapshot,
            latest.updated_at,
          )
        : latest;
    knownVersions.set(recovered.id, recovered.updated_at);
    restoreConversation(recovered);
    upsertConversation(recovered);
  });
}

async function switchConversation(action: () => Promise<void>): Promise<void> {
  const state = useStore.getState();
  if (state.responding || state.sendStarting || state.conversationSwitching)
    return;
  // 异步保存或读取期间阻止新请求，避免旧响应覆盖新会话。
  useStore.setState({ conversationSwitching: true });
  try {
    await action();
  } finally {
    useStore.setState({ conversationSwitching: false });
  }
}

export async function createConversation(): Promise<void> {
  await switchConversation(async () => {
    await flushConversation();
    const id = nanoid();
    useStore.setState(emptyConversation(id));
    writeBrowserStorage("local", ACTIVE_CONVERSATION_KEY, id);
    setEnableWebSearch(true);
  });
}

export async function openConversation(id: string): Promise<void> {
  if (
    useStore.getState().conversationId === id &&
    !useStore.getState().remoteRunning
  ) {
    return;
  }
  await switchConversation(async () => {
    await flushConversation();
    const detail = await loadConversation(id);
    restoreConversation(detail);
    writeBrowserStorage("local", ACTIVE_CONVERSATION_KEY, id);
  });
}

export async function removeConversation(id: string): Promise<void> {
  await switchConversation(async () => {
    const currentId = useStore.getState().conversationId;
    await flushConversation();
    await deleteConversationAPI(id, knownVersions.get(id));
    knownVersions.delete(id);
    useStore.setState((state) => ({
      conversations: state.conversations.filter((item) => item.id !== id),
    }));
    if (currentId === id) {
      const nextId = nanoid();
      useStore.setState(emptyConversation(nextId));
      writeBrowserStorage("local", ACTIVE_CONVERSATION_KEY, nextId);
      setEnableWebSearch(true);
    }
  });
}

export async function sendMessage(
  content?: string,
  {
    interruptFeedback,
    resources,
  }: {
    interruptFeedback?: string;
    resources?: Array<Resource>;
  } = {},
  options: { abortSignal?: AbortSignal } = {},
) {
  if (
    useStore.getState().sendStarting ||
    useStore.getState().responding ||
    useStore.getState().conversationSwitching
  ) {
    return;
  }
  useStore.setState({ sendStarting: true });
  try {
    await initializeConversationHistory();
  } finally {
    useStore.setState({ sendStarting: false });
  }
  const current = useStore.getState();
  if (current.responding || current.conversationSwitching) return;
  if (current.remoteRunning) {
    toast("此会话仍在其他标签页运行，请稍后刷新历史记录。");
    return;
  }
  if (interruptFeedback && current.conversationStatus === "needs_retry") {
    toast("上次研究已中断，请重新提问。");
    return;
  }

  const selection = resolveResearchSelection(
    current.researchMode,
    current.selectedResources,
    resources,
  );
  if (!selection.valid) {
    toast("请先选择至少一份资料再提问。");
    return;
  }

  const conversationId = current.conversationId;
  // 每轮新研究使用新运行 ID；计划审核反馈沿用该轮 ID 才能恢复中断点。
  const runThreadId = interruptFeedback ? current.activeRunThreadId : nanoid();
  if (!runThreadId) {
    toast("研究状态已失效，请重新提问。");
    return;
  }
  const history = interruptFeedback
    ? undefined
    : boundedConversationHistory(current);
  writeBrowserStorage(
    "session",
    ACTIVE_RUN_OWNER_KEY,
    `${conversationId}:${runThreadId}`,
  );
  useStore.setState({
    activeRunThreadId: runThreadId,
    threadId: runThreadId,
    conversationStatus: "running",
  });

  if (content != null) {
    appendMessage({
      id: nanoid(),
      threadId: runThreadId,
      role: "user",
      content: content,
      contentChunks: [content],
      resources: selection.resources,
      interruptFeedback,
    });
  }

  // 开始模型请求前先抢占会话版本，避免两个标签页在自动保存间隔内同时研究。
  setResponding(true);
  try {
    const replayParams = new URLSearchParams(location.search);
    if (
      !env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY &&
      !replayParams.has("mock") &&
      !replayParams.has("replay")
    ) {
      await flushConversation();
    }
  } catch (error) {
    if (
      readBrowserStorage("session", ACTIVE_RUN_OWNER_KEY) ===
      `${conversationId}:${runThreadId}`
    ) {
      removeBrowserStorage("session", ACTIVE_RUN_OWNER_KEY);
    }
    const latest = useStore.getState();
    const messages = new Map(latest.messages);
    for (const [id, message] of messages) {
      if (message.threadId === runThreadId) {
        messages.set(id, { ...message, historyIncomplete: true });
      }
    }
    // 失败的提问仍留在页面供复制；不会被带入下一轮追问。
    restoringSnapshot = true;
    try {
      useStore.setState({
        messages,
        conversationStatus: "needs_retry",
        responding: false,
      });
    } finally {
      restoringSnapshot = false;
    }
    toast.error(
      error instanceof Error ? error.message : "保存会话失败，请刷新后重试。",
    );
    return;
  }

  const settings = getChatStreamSettings();
  const stream = chatStream(
    content ?? "[REPLAY]",
    {
      thread_id: runThreadId,
      history,
      interrupt_feedback: interruptFeedback,
      resources: selection.resources,
      auto_accepted_plan: settings.autoAcceptedPlan,
      enable_clarification: settings.enableClarification ?? false,
      max_clarification_rounds: settings.maxClarificationRounds ?? 3,
      enable_deep_thinking: settings.enableDeepThinking ?? false,
      enable_background_investigation:
        settings.enableBackgroundInvestigation ?? true,
      enable_web_search: selection.enableWebSearch,
      max_plan_iterations: settings.maxPlanIterations,
      max_step_num: settings.maxStepNum,
      max_search_results: settings.maxSearchResults,
      report_style: settings.reportStyle,
      mcp_settings: settings.mcpSettings,
    },
    options,
  );

  let messageId: string | undefined;
  let sawInterrupt = false;
  let hadError = false;
  const pendingUpdates = new Map<string, Message>();
  let updateTimer: NodeJS.Timeout | undefined;

  const scheduleUpdate = () => {
    if (updateTimer) clearTimeout(updateTimer);
    updateTimer = setTimeout(() => {
      // Batch update message status
      if (pendingUpdates.size > 0) {
        useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
        pendingUpdates.clear();
      }
    }, 16); // ~60fps
  };

  try {
    for await (const event of stream) {
      const { type, data } = event;
      let message: Message | undefined;

      if (type === "error") {
        hadError = true;
        // Server sent an error event - check if it's user cancellation
        if (data.reason !== "cancelled") {
          toast(
            data.error || "An error occurred while generating the response.",
          );
        }
        break;
      }
      if (type === "interrupt") sawInterrupt = true;
      // Handle citations event: store citations for the current research
      if (type === "citations") {
        const ongoingResearchId = useStore.getState().ongoingResearchId;
        if (ongoingResearchId && data.citations) {
          useStore.getState().setCitations(ongoingResearchId, data.citations);
        }
        continue;
      }

      // Handle tool_call_result specially: use the message that contains the tool call
      if (type === "tool_call_result") {
        message = findMessageByToolCallId(data.tool_call_id);
        if (message) {
          // Use the found message's ID, not data.id
          messageId = message.id;
        } else {
          // Shouldn't happen, but handle gracefully
          if (process.env.NODE_ENV === "development") {
            console.warn(
              `Tool call result without matching message: ${data.tool_call_id}`,
            );
          }
          continue; // Skip this event
        }
      } else {
        // For other event types, use data.id
        messageId = data.id;

        if (!existsMessage(messageId)) {
          message = {
            id: messageId,
            threadId: data.thread_id,
            agent: data.agent,
            role: data.role,
            content: "",
            contentChunks: [],
            reasoningContent: "",
            reasoningContentChunks: [],
            isStreaming: true,
            interruptFeedback,
          };
          appendMessage(message);
        }
      }

      message ??= getMessage(messageId);
      if (message) {
        message = mergeMessage(message, event);
        // Collect pending messages for update, instead of updating immediately.
        pendingUpdates.set(message.id, message);
        scheduleUpdate();
      }
    }
  } catch (error) {
    hadError = true;
    const isAborted = (error as Error).name === "AbortError";
    if (!isAborted) {
      toast(
        "An error occurred while generating the response. Please try again.",
      );
    }
    // Update message status.
    if (messageId != null) {
      const message = getMessage(messageId);
      if (message?.isStreaming) {
        message.isStreaming = false;
        useStore.getState().updateMessage(message);
      }
    }
    useStore.getState().setOngoingResearch(null);
  } finally {
    if (
      readBrowserStorage("session", ACTIVE_RUN_OWNER_KEY) ===
      `${conversationId}:${runThreadId}`
    ) {
      removeBrowserStorage("session", ACTIVE_RUN_OWNER_KEY);
    }
    setResponding(false);
    // Ensure all pending updates are processed.
    if (updateTimer) clearTimeout(updateTimer);
    if (pendingUpdates.size > 0) {
      useStore.getState().updateMessages(Array.from(pendingUpdates.values()));
    }
    if (useStore.getState().conversationId === conversationId) {
      const currentMessages = useStore.getState().messages;
      const status = completedRunStatus(
        currentMessages,
        runThreadId,
        hadError,
        sawInterrupt,
      );
      const unfinished = [...currentMessages.values()]
        .filter(
          (message) =>
            message.threadId === runThreadId &&
            (Boolean(message.isStreaming) ||
              (status === "needs_retry" &&
                message.role === "assistant" &&
                message.finishReason !== "stop")),
        )
        .map((message) => ({
          ...message,
          isStreaming: false,
          historyIncomplete: true,
        }));
      if (unfinished.length > 0) {
        useStore.getState().updateMessages(unfinished);
      }
      useStore.setState({
        conversationStatus: status,
        ongoingResearchId: null,
      });
      try {
        await flushConversation();
      } catch (error) {
        console.error("Failed to save conversation:", error);
      }
    }
  }
}

function setResponding(value: boolean) {
  useStore.setState({ responding: value });
}

function existsMessage(id: string) {
  return useStore.getState().messageIds.includes(id);
}

function getMessage(id: string) {
  return useStore.getState().messages.get(id);
}

function findMessageByToolCallId(toolCallId: string) {
  return Array.from(useStore.getState().messages.values())
    .reverse()
    .find((message) => {
      if (message.toolCalls) {
        return message.toolCalls.some((toolCall) => toolCall.id === toolCallId);
      }
      return false;
    });
}

function appendMessage(message: Message) {
  if (
    message.agent === "coder" ||
    message.agent === "reporter" ||
    message.agent === "researcher" ||
    message.agent === "analyst"
  ) {
    if (!getOngoingResearchId()) {
      const id = message.id;
      appendResearch(id);
      openResearch(id);
    }
    appendResearchActivity(message);
  }
  useStore.getState().appendMessage(message);
}

function getOngoingResearchId() {
  return useStore.getState().ongoingResearchId;
}

function appendResearch(researchId: string) {
  let planMessage: Message | undefined;
  let userQuery: string | undefined;
  const reversedMessageIds = [...useStore.getState().messageIds].reverse();
  for (const messageId of reversedMessageIds) {
    const message = getMessage(messageId);
    if (!planMessage && message?.agent === "planner") {
      planMessage = message;
    }
    if (!userQuery && message?.role === "user") {
      userQuery = message.content;
    }
    if (planMessage && userQuery) {
      break;
    }
  }
  const messageIds = [researchId];
  messageIds.unshift(planMessage!.id);
  useStore.setState({
    ongoingResearchId: researchId,
    researchIds: [...useStore.getState().researchIds, researchId],
    researchPlanIds: new Map(useStore.getState().researchPlanIds).set(
      researchId,
      planMessage!.id,
    ),
    researchActivityIds: new Map(useStore.getState().researchActivityIds).set(
      researchId,
      messageIds,
    ),
    researchQueries: new Map(useStore.getState().researchQueries).set(
      researchId,
      userQuery ?? "",
    ),
  });
}

function appendResearchActivity(message: Message) {
  const researchId = getOngoingResearchId();
  if (researchId) {
    const researchActivityIds = useStore.getState().researchActivityIds;
    const current = researchActivityIds.get(researchId)!;
    if (!current.includes(message.id)) {
      useStore.setState({
        researchActivityIds: new Map(researchActivityIds).set(researchId, [
          ...current,
          message.id,
        ]),
      });
    }
    if (message.agent === "reporter") {
      useStore.setState({
        researchReportIds: new Map(useStore.getState().researchReportIds).set(
          researchId,
          message.id,
        ),
      });
    }
  }
}

export function openResearch(researchId: string | null) {
  useStore.getState().openResearch(researchId);
}

export function closeResearch() {
  useStore.getState().closeResearch();
}

export async function listenToPodcast(researchId: string) {
  const planMessageId = useStore.getState().researchPlanIds.get(researchId);
  const reportMessageId = useStore.getState().researchReportIds.get(researchId);
  if (planMessageId && reportMessageId) {
    const planMessage = getMessage(planMessageId)!;
    const title = parseJSON(planMessage.content, { title: "Untitled" }).title;
    const reportMessage = getMessage(reportMessageId);
    if (reportMessage?.content) {
      appendMessage({
        id: nanoid(),
        threadId:
          useStore.getState().activeRunThreadId ??
          useStore.getState().conversationId,
        role: "user",
        content: "Please generate a podcast for the above research.",
        contentChunks: [],
      });
      const podCastMessageId = nanoid();
      const podcastObject = { title, researchId };
      const podcastMessage: Message = {
        id: podCastMessageId,
        threadId:
          useStore.getState().activeRunThreadId ??
          useStore.getState().conversationId,
        role: "assistant",
        agent: "podcast",
        content: JSON.stringify(podcastObject),
        contentChunks: [],
        reasoningContent: "",
        reasoningContentChunks: [],
        isStreaming: true,
      };
      appendMessage(podcastMessage);
      // Generating podcast...
      let audioUrl: string | undefined;
      try {
        audioUrl = await generatePodcast(reportMessage.content);
      } catch (e) {
        console.error(e);
        useStore.setState((state) => ({
          messages: new Map(useStore.getState().messages).set(
            podCastMessageId,
            {
              ...state.messages.get(podCastMessageId)!,
              content: JSON.stringify({
                ...podcastObject,
                error: e instanceof Error ? e.message : "Unknown error",
              }),
              isStreaming: false,
            },
          ),
        }));
        toast("An error occurred while generating podcast. Please try again.");
        return;
      }
      useStore.setState((state) => ({
        messages: new Map(useStore.getState().messages).set(podCastMessageId, {
          ...state.messages.get(podCastMessageId)!,
          content: JSON.stringify({ ...podcastObject, audioUrl }),
          isStreaming: false,
        }),
      }));
    }
  }
}

export function useResearchMessage(researchId: string) {
  return useStore(
    useShallow((state) => {
      const messageId = state.researchPlanIds.get(researchId);
      return messageId ? state.messages.get(messageId) : undefined;
    }),
  );
}

export function getResearchQuery(researchId: string): string {
  return useStore.getState().researchQueries.get(researchId) ?? "";
}

export function useMessage(messageId: string | null | undefined) {
  return useStore(
    useShallow((state) =>
      messageId ? state.messages.get(messageId) : undefined,
    ),
  );
}

export function useMessageIds() {
  return useStore(useShallow((state) => state.messageIds));
}

export function useRenderableMessageIds() {
  return useStore(
    useShallow((state) => {
      // Filter to only messages that will actually render in MessageListView
      // This prevents duplicate keys and React warnings when messages change state
      return state.messageIds.filter((messageId) => {
        const message = state.messages.get(messageId);
        if (!message) return false;

        // Only include messages that match MessageListItem rendering conditions
        // These are the same conditions checked in MessageListItem component
        const isPlanner = message.agent === "planner";
        const isPodcast = message.agent === "podcast";
        const isStartOfResearch = state.researchIds.includes(messageId);

        // Planner, podcast, and research cards always render (they have their own content)
        if (isPlanner || isPodcast || isStartOfResearch) {
          return true;
        }

        // For user and coordinator messages, only include if they have content
        // This prevents empty dividers from appearing in the UI
        if (message.role === "user" || message.agent === "coordinator") {
          return !!message.content;
        }

        return false;
      });
    }),
  );
}

export function useLastInterruptMessage() {
  return useStore(
    useShallow((state) => {
      if (state.messageIds.length >= 2) {
        const lastMessage = state.messages.get(
          state.messageIds[state.messageIds.length - 1]!,
        );
        return lastMessage?.finishReason === "interrupt" ? lastMessage : null;
      }
      return null;
    }),
  );
}

export function useLastFeedbackMessageId() {
  const waitingForFeedbackMessageId = useStore(
    useShallow((state) => {
      if (state.messageIds.length >= 2) {
        const lastMessage = state.messages.get(
          state.messageIds[state.messageIds.length - 1]!,
        );
        if (lastMessage && lastMessage.finishReason === "interrupt") {
          return state.messageIds[state.messageIds.length - 2];
        }
      }
      return null;
    }),
  );
  return waitingForFeedbackMessageId;
}

export function useToolCalls() {
  return useStore(
    useShallow((state) => {
      return state.messageIds
        ?.map((id) => getMessage(id)?.toolCalls)
        .filter((toolCalls) => toolCalls != null)
        .flat();
    }),
  );
}

export function useCitations(researchId: string | null | undefined) {
  return useStore(
    useShallow((state) =>
      researchId ? (state.researchCitations.get(researchId) ?? []) : [],
    ),
  );
}

export function getCitations(researchId: string): Citation[] {
  return useStore.getState().researchCitations.get(researchId) ?? [];
}
