import type { Message } from "~/core/messages";
import {
  boundedConversationHistory,
  completedRunStatus,
  conversationTitle,
  makeConversationSnapshot,
  resolveResearchSelection,
  restoreConversationSnapshot,
} from "~/core/store/conversation-utils";

const user: Message = {
  id: "question",
  threadId: "run-1",
  role: "user",
  content: "请解释论文",
  contentChunks: ["请解释论文"],
};
const report: Message = {
  id: "report",
  threadId: "run-1",
  role: "assistant",
  agent: "reporter",
  content: "论文使用了对照实验。",
  contentChunks: ["论文使用了对照实验。"],
  finishReason: "stop",
};

test("restores report, citations and selected resources from a JSON snapshot", () => {
  const state = {
    messageIds: [user.id, report.id],
    messages: new Map([
      [user.id, user],
      [report.id, report],
    ]),
    researchIds: [report.id],
    researchPlanIds: new Map([[report.id, "plan"]]),
    researchReportIds: new Map([[report.id, report.id]]),
    researchActivityIds: new Map([[report.id, ["plan", report.id]]]),
    researchQueries: new Map([[report.id, user.content]]),
    researchCitations: new Map([
      [
        report.id,
        [{ url: "qdrant://paper#page=2", title: "论文", page_number: 2 }],
      ],
    ]),
    openResearchId: report.id,
    activeRunThreadId: "run-1",
    selectedResources: [{ uri: "qdrant://paper", title: "论文" }],
    researchMode: "local" as const,
  };

  const serialized = JSON.parse(
    JSON.stringify(makeConversationSnapshot(state)),
  );
  const restored = restoreConversationSnapshot(serialized);

  expect(restored.messages.get(report.id)?.content).toBe(report.content);
  expect(restored.researchCitations.get(report.id)?.[0]?.page_number).toBe(2);
  expect(restored.selectedResources[0]?.uri).toBe("qdrant://paper");
  expect(restored.researchMode).toBe("local");
  expect(conversationTitle(restored)).toBe(user.content);
});

test("follow-up context excludes tool chatter and feedback and has a size bound", () => {
  const feedback: Message = {
    ...user,
    id: "feedback",
    content: "Let's start.",
    interruptFeedback: "accepted",
  };
  const tool: Message = {
    ...report,
    id: "tool",
    role: "tool",
    content: "Internal tool data",
  };
  const state = {
    messageIds: [user.id, feedback.id, tool.id, report.id],
    messages: new Map([
      [user.id, user],
      [feedback.id, feedback],
      [tool.id, tool],
      [report.id, report],
    ]),
  };

  expect(boundedConversationHistory(state)).toEqual([
    { role: "user", content: user.content },
    { role: "assistant", content: report.content },
  ]);

  const longMessages = new Map<string, Message>();
  const longIds = Array.from({ length: 10 }, (_, index) => `long-${index}`);
  for (const id of longIds) {
    longMessages.set(id, { ...report, id, content: "字".repeat(8000) });
  }
  const bounded = boundedConversationHistory({
    messageIds: longIds,
    messages: longMessages,
  });
  expect(bounded.length).toBeLessThanOrEqual(4);
  expect(
    bounded.reduce((length, item) => length + item.content.length, 0),
  ).toBeLessThanOrEqual(12000);
});

test("restored interrupted output stops spinning and stays out of follow-up context", () => {
  const partial: Message = {
    ...report,
    id: "partial",
    content: "尚未完成的报告片段",
    isStreaming: true,
    finishReason: undefined,
  };
  const snapshot = makeConversationSnapshot({
    messageIds: [user.id, partial.id],
    messages: new Map([
      [user.id, user],
      [partial.id, partial],
    ]),
    researchIds: [partial.id],
    researchPlanIds: new Map(),
    researchReportIds: new Map([[partial.id, partial.id]]),
    researchActivityIds: new Map(),
    researchQueries: new Map(),
    researchCitations: new Map(),
    openResearchId: partial.id,
    activeRunThreadId: "run-1",
    selectedResources: [],
    researchMode: "web",
  });

  const restored = restoreConversationSnapshot(snapshot, true);
  expect(restored.messages.get(partial.id)?.isStreaming).toBe(false);
  expect(boundedConversationHistory(restored)).toEqual([
    { role: "user", content: user.content },
  ]);
});

test("restored non-streaming partial output is excluded from follow-up context", () => {
  const partial: Message = {
    ...report,
    id: "partial-after-network-error",
    content: "网络断开前的半截报告",
    isStreaming: false,
    finishReason: undefined,
  };
  const snapshot = makeConversationSnapshot({
    messageIds: [user.id, partial.id],
    messages: new Map([
      [user.id, user],
      [partial.id, partial],
    ]),
    researchIds: [partial.id],
    researchPlanIds: new Map(),
    researchReportIds: new Map([[partial.id, partial.id]]),
    researchActivityIds: new Map(),
    researchQueries: new Map(),
    researchCitations: new Map(),
    openResearchId: partial.id,
    activeRunThreadId: "run-1",
    selectedResources: [],
    researchMode: "web",
  });

  const restored = restoreConversationSnapshot(snapshot, true);
  expect(restored.messages.get(partial.id)?.historyIncomplete).toBe(true);
  expect(boundedConversationHistory(restored)).toEqual([
    { role: "user", content: user.content },
  ]);
});

test("a stream ending without a finished answer requires retry", () => {
  const partial: Message = {
    ...report,
    id: "partial-eof",
    finishReason: undefined,
    isStreaming: true,
  };
  expect(
    completedRunStatus(new Map([[partial.id, partial]]), "run-1", false, false),
  ).toBe("needs_retry");
  expect(
    completedRunStatus(new Map([[report.id, report]]), "run-1", false, false),
  ).toBe("idle");
  expect(
    completedRunStatus(new Map([[report.id, report]]), "run-1", false, true),
  ).toBe("waiting_feedback");
});

test("local and hybrid research require a selected document even outside the input box", () => {
  expect(resolveResearchSelection("local", []).valid).toBe(false);
  expect(resolveResearchSelection("hybrid", []).valid).toBe(false);
  expect(resolveResearchSelection("web", []).valid).toBe(true);
  const selected = [{ uri: "qdrant://paper", title: "论文" }];
  expect(resolveResearchSelection("local", selected)).toEqual({
    valid: true,
    resources: selected,
    enableWebSearch: false,
  });
});
