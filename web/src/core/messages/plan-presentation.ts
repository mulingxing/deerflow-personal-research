import { parseJSON } from "../utils/json";

export interface PlanStep {
  title?: string;
  description?: string;
  tools?: string[];
}

export interface PlanPresentation {
  plan: {
    title?: string;
    thought?: string;
    steps: PlanStep[];
  };
  invalidPlan: boolean;
  canStartResearch: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parseCompleteJSON(content: string): unknown {
  const raw = content.trim();
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    // 有些模型会先写一段说明，再把真正的计划放进唯一的 JSON 代码块。
    // 只接受完整且唯一的代码块；块后有正文或出现多个代码块时继续按无效计划处理。
    const fences = [...raw.matchAll(/```/g)];
    if (fences.length !== 2) return null;
    const start = fences[0]!.index + 3;
    const end = fences[1]!.index;
    if (raw.slice(end + 3).trim()) return null;
    const enclosed = raw.slice(start, end).trim();
    const candidate = enclosed.replace(/^(?:json|js|ts|plaintext)\s*/i, "");
    try {
      return JSON.parse(candidate) as unknown;
    } catch {
      return null;
    }
  }
}

/** 规划器偶尔返回未经检索的 Markdown 正文；不能把它当成研究结果展示。 */
export function getPlanPresentation(
  content: string,
  isStreaming: boolean,
): PlanPresentation {
  const startsWithJSON = /^\s*(?:```(?:json|js|ts|plaintext)?\s*)?[\[{]/i.test(
    content,
  );
  if (!startsWithJSON && !content.includes("```")) {
    return {
      plan: { steps: [] },
      invalidPlan: !isStreaming,
      canStartResearch: false,
    };
  }

  // 只有流式阶段才宽松解析；完整计划必须是合法 JSON，避免误开放“开始研究”。
  const parsed = isStreaming
    ? startsWithJSON
      ? parseJSON<unknown>(content, null)
      : null
    : parseCompleteJSON(content);
  const data = isRecord(parsed) ? parsed : {};
  const rawSteps = Array.isArray(parsed) ? parsed : data.steps;
  // 与后端 Plan.Step 的必需字段保持一致，避免将无法执行的内容误当成有效计划。
  const canStartResearch =
    Array.isArray(rawSteps) &&
    rawSteps.length > 0 &&
    rawSteps.every(
      (step) =>
        isRecord(step) &&
        typeof step.title === "string" &&
        step.title.trim().length > 0 &&
        typeof step.description === "string" &&
        step.description.trim().length > 0 &&
        typeof step.need_search === "boolean" &&
        (step.step_type === "research" ||
          step.step_type === "analysis" ||
          step.step_type === "processing"),
    );
  const steps = Array.isArray(rawSteps)
    ? rawSteps.filter(isRecord).flatMap((step) => {
        const title = typeof step.title === "string" ? step.title : undefined;
        const description =
          typeof step.description === "string" ? step.description : undefined;
        if (!title?.trim() && !description?.trim()) {
          return [];
        }
        return [
          {
            title,
            description,
            tools: Array.isArray(step.tools)
              ? step.tools.filter(
                  (tool): tool is string => typeof tool === "string",
                )
              : undefined,
          },
        ];
      })
    : [];

  const invalidPlan = !isStreaming && !canStartResearch;
  return {
    // 格式异常时不透出未经检索的标题、说明或步骤，避免用户误当作研究结论。
    plan: invalidPlan
      ? { steps: [] }
      : {
          title: typeof data.title === "string" ? data.title : undefined,
          thought: typeof data.thought === "string" ? data.thought : undefined,
          steps,
        },
    // 流式 JSON 尚未写出步骤时继续显示已到达的标题/说明；结束后再判定计划是否有效。
    invalidPlan,
    canStartResearch,
  };
}
