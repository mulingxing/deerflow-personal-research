import { parse } from "best-effort-json-parser";

import { parseBestEffortJSON, parseJSON } from "../src/core/utils/json";

describe("宽松 JSON 解析的开发环境提示", () => {
  it("普通文本不会被当成计划，也不会触发额外 token 错误", () => {
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const originalCallback = parse.onExtraToken;

    try {
      const fallback = { title: "等待计划" };
      expect(parseJSON("This is just plain text, not JSON", fallback)).toBe(
        fallback,
      );
      expect(consoleError).not.toHaveBeenCalled();
      expect(parse.onExtraToken).toBe(originalCallback);
    } finally {
      consoleError.mockRestore();
    }
  });

  it("保留未结束计划中已写入的嵌套列表和后续字段", () => {
    const partialPlan = '{"steps":[],"thought":"still streaming';
    expect(parseJSON(partialPlan, {})).toEqual({
      steps: [],
      thought: "still streaming",
    });
  });

  it("仅忽略可恢复的剩余字符，并恢复依赖库回调", () => {
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const originalCallback = parse.onExtraToken;

    try {
      expect(parseBestEffortJSON('{"title":"A"} trailing text')).toEqual({
        title: "A",
      });
      expect(consoleError).not.toHaveBeenCalled();
      expect(parse.onExtraToken).toBe(originalCallback);
    } finally {
      consoleError.mockRestore();
    }
  });

  it("真正的解析异常仍会抛出并恢复回调", () => {
    const consoleError = jest
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const originalCallback = parse.onExtraToken;

    try {
      expect(() => parseBestEffortJSON('{"bad": @}')).toThrow();
      expect(consoleError).toHaveBeenCalled();
      expect(parse.onExtraToken).toBe(originalCallback);
      expect(parseJSON('{"bad": @}', { safe: true })).toEqual({ safe: true });
    } finally {
      consoleError.mockRestore();
    }
  });
});
