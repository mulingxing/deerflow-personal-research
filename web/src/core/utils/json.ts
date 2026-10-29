import { parse } from "best-effort-json-parser";

/**
 * 宽松解析用于流式消息，剩余字符只表示本次解析未消费完输入。
 * 依赖库默认把这种可恢复情况写入 console.error，会触发 Next.js 开发错误弹窗。
 * 解析过程是同步的，因此仅在这次调用中关闭该提示，并在结束后恢复原回调。
 * 真正的解析异常仍由调用方捕获并使用后备值。
 */
export function parseBestEffortJSON(json: string): unknown {
  const originalOnExtraToken = parse.onExtraToken;
  parse.onExtraToken = () => undefined;
  try {
    return parse(json);
  } finally {
    parse.onExtraToken = originalOnExtraToken;
  }
}

/**
 * Extract valid JSON from content that may have extra tokens.
 * Finds the last closing brace/bracket that could be valid JSON.
 */
function extractValidJSON(content: string): string {
  let braceCount = 0;
  let bracketCount = 0;
  let inString = false;
  let escapeNext = false;
  let lastValidEnd = -1;

  for (let i = 0; i < content.length; i++) {
    const char = content[i];

    if (escapeNext) {
      escapeNext = false;
      continue;
    }

    if (inString && char === "\\") {
      escapeNext = true;
      continue;
    }

    if (char === '"') {
      inString = !inString;
      continue;
    }

    if (inString) {
      continue;
    }

    if (char === "{") {
      braceCount++;
    } else if (char === "}") {
      if (braceCount > 0) {
        braceCount--;
        if (braceCount === 0 && bracketCount === 0) {
          lastValidEnd = i;
        }
      }
    } else if (char === "[") {
      bracketCount++;
    } else if (char === "]") {
      if (bracketCount > 0) {
        bracketCount--;
        if (braceCount === 0 && bracketCount === 0) {
          lastValidEnd = i;
        }
      }
    }
  }

  if (lastValidEnd > 0) {
    return content.substring(0, lastValidEnd + 1);
  }

  return content;
}

export function parseJSON<T>(json: string | null | undefined, fallback: T) {
  if (!json) {
    return fallback;
  }
  try {
    let raw = json
      .trim()
      .replace(/^```json\s*/, "")
      .replace(/^```js\s*/, "")
      .replace(/^```ts\s*/, "")
      .replace(/^```plaintext\s*/, "")
      .replace(/^```\s*/, "")
      .replace(/\s*```$/, "");

    // First attempt: try to extract valid JSON to remove extra tokens
    if (raw.startsWith("{") || raw.startsWith("[")) {
      raw = extractValidJSON(raw);
    }

    // 解析流式内容；顶层类型不符时使用后备值，避免把普通文本当成计划或列表。
    const parsed = parseBestEffortJSON(raw);
    if (Array.isArray(fallback)) {
      return (Array.isArray(parsed) ? parsed : fallback) as T;
    }
    if (fallback !== null && typeof fallback === "object") {
      return (
        parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
          ? parsed
          : fallback
      ) as T;
    }
    return parsed as T;
  } catch {
    // Fallback: try to extract meaningful content from malformed JSON
    // This is a last-resort attempt to salvage partial data
    return fallback;
  }
}
