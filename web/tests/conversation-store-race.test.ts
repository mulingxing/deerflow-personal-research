import { chatStream } from "../src/core/api";
import {
  getConversation,
  listConversations,
  saveConversation,
  type ConversationDetail,
} from "../src/core/api/history";
import {
  createConversation,
  initializeConversationHistory,
  openConversation,
  recoverStoppedConversation,
  sendMessage,
  useStore,
} from "../src/core/store/store";

jest.mock("../src/core/api", () => ({
  chatStream: jest.fn(async function* () {}),
  generatePodcast: jest.fn(),
}));
jest.mock("nanoid", () => {
  let next = 0;
  return { nanoid: () => `test-id-${++next}` };
});
jest.mock("sonner", () => ({
  toast: Object.assign(jest.fn(), { error: jest.fn() }),
}));
jest.mock("~/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: false },
}));
jest.mock("../src/core/api/history", () => ({
  listConversations: jest.fn(),
  getConversation: jest.fn(),
  saveConversation: jest.fn(),
  deleteConversation: jest.fn(),
}));
jest.mock("../src/core/store/settings-store", () => ({
  getChatStreamSettings: jest.fn(() => ({
    enableWebSearch: true,
    autoAcceptedPlan: true,
    maxPlanIterations: 1,
    maxStepNum: 1,
    maxSearchResults: 2,
  })),
  setEnableWebSearch: jest.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

test("initial load and conversation switches reject competing sends", async () => {
  window.localStorage.clear();
  const listing = deferred<[]>();
  jest.mocked(listConversations).mockReturnValue(listing.promise);
  let version = 0;
  jest.mocked(saveConversation).mockImplementation(
    async (id, title, status, snapshot): Promise<ConversationDetail> => ({
      id,
      title,
      status,
      snapshot,
      created_at: "2026-10-26T00:00:00Z",
      updated_at: `version-${++version}`,
    }),
  );

  const first = sendMessage("第一条问题");
  expect(useStore.getState().sendStarting).toBe(true);
  await sendMessage("并发问题");
  listing.resolve([]);
  await first;
  expect(useStore.getState().messageIds).toHaveLength(1);
  expect(
    jest.mocked(saveConversation).mock.invocationCallOrder[0],
  ).toBeLessThan(jest.mocked(chatStream).mock.invocationCallOrder[0]!);

  const saving = deferred<ConversationDetail>();
  jest.mocked(saveConversation).mockReturnValueOnce(saving.promise);
  const creating = createConversation();
  expect(useStore.getState().conversationSwitching).toBe(true);
  await sendMessage("切换中不应发送");
  expect(useStore.getState().messageIds).toHaveLength(1);
  const state = useStore.getState();
  saving.resolve({
    id: state.conversationId,
    title: "第一条问题",
    status: state.conversationStatus,
    snapshot: {
      version: 1,
      messageIds: [],
      messages: [],
      researchIds: [],
      researchPlanIds: [],
      researchReportIds: [],
      researchActivityIds: [],
      researchQueries: [],
      researchCitations: [],
      openResearchId: null,
      activeRunThreadId: null,
      selectedResources: [],
      researchMode: "web",
    },
    created_at: "2026-10-26T00:00:00Z",
    updated_at: `version-${++version}`,
  });
  await creating;
  expect(useStore.getState().messageIds).toHaveLength(0);

  const loading = deferred<ConversationDetail>();
  jest.mocked(getConversation).mockReturnValueOnce(loading.promise);
  const opening = openConversation("conversation_999");
  expect(useStore.getState().conversationSwitching).toBe(true);
  await sendMessage("读取中不应发送");
  loading.resolve({
    id: "conversation_999",
    title: "旧会话",
    status: "idle",
    snapshot: {
      version: 1,
      messageIds: [],
      messages: [],
      researchIds: [],
      researchPlanIds: [],
      researchReportIds: [],
      researchActivityIds: [],
      researchQueries: [],
      researchCitations: [],
      openResearchId: null,
      activeRunThreadId: null,
      selectedResources: [],
      researchMode: "web",
    },
    created_at: "2026-10-26T00:00:00Z",
    updated_at: "version-9",
  });
  await opening;
  expect(useStore.getState().conversationId).toBe("conversation_999");
  expect(useStore.getState().messageIds).toHaveLength(0);

  const running: ConversationDetail = {
    id: "conversation_run",
    title: "另一标签页的研究",
    status: "running",
    snapshot: {
      version: 1,
      messageIds: [],
      messages: [],
      researchIds: [],
      researchPlanIds: [],
      researchReportIds: [],
      researchActivityIds: [],
      researchQueries: [],
      researchCitations: [],
      openResearchId: null,
      activeRunThreadId: "remote-run",
      selectedResources: [],
      researchMode: "web",
    },
    created_at: "2026-10-26T00:00:00Z",
    updated_at: "version-10",
  };
  jest.mocked(getConversation).mockResolvedValueOnce(running);
  jest.mocked(saveConversation).mockClear();
  await openConversation(running.id);
  expect(useStore.getState().remoteRunning).toBe(true);
  expect(saveConversation).not.toHaveBeenCalled();
  await sendMessage("不能抢占另一标签页");
  expect(saveConversation).not.toHaveBeenCalled();

  jest.mocked(getConversation).mockResolvedValueOnce(running);
  await recoverStoppedConversation();
  expect(saveConversation).toHaveBeenCalledWith(
    running.id,
    running.title,
    "needs_retry",
    running.snapshot,
    running.updated_at,
  );
  expect(useStore.getState().remoteRunning).toBe(false);
  expect(useStore.getState().conversationStatus).toBe("needs_retry");

  const priorStreams = jest.mocked(chatStream).mock.calls.length;
  jest.mocked(saveConversation).mockRejectedValueOnce(new Error("HTTP 409"));
  await sendMessage("冲突时不调用模型");
  expect(jest.mocked(chatStream).mock.calls).toHaveLength(priorStreams);
  expect(useStore.getState().conversationStatus).toBe("needs_retry");
  const failedQuestion = useStore
    .getState()
    .messages.get(useStore.getState().messageIds.at(-1)!);
  expect(failedQuestion?.historyIncomplete).toBe(true);
});
