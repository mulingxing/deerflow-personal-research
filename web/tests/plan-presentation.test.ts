import { getPlanPresentation } from "../src/core/messages/plan-presentation";

describe("计划卡内容展示", () => {
  it("规划器返回未经检索的 Markdown 报告时不暴露正文", () => {
    const report =
      "# 星河学习小组“三步复习法”核查报告\n\n## 关键点\n\n- 第一步：阅读论文。";

    expect(getPlanPresentation(report, false)).toEqual({
      plan: { steps: [] },
      invalidPlan: true,
      canStartResearch: false,
    });
    expect(JSON.stringify(getPlanPresentation(report, false))).not.toContain(
      "第一步：阅读论文",
    );
  });

  it("有效计划继续按标题、说明和步骤展示", () => {
    const content = JSON.stringify({
      title: "学习计划",
      thought: "先查资料",
      steps: [
        {
          title: "定位资料",
          description: "检索所选文件",
          need_search: false,
          step_type: "analysis",
        },
      ],
    });

    expect(getPlanPresentation(content, false)).toEqual({
      plan: {
        title: "学习计划",
        thought: "先查资料",
        steps: [{ title: "定位资料", description: "检索所选文件" }],
      },
      invalidPlan: false,
      canStartResearch: true,
    });
  });

  it("后端可接受的步骤数组也能按计划展示", () => {
    const content =
      '[{"title":"检索资料","description":"查找笔记","need_search":true,"step_type":"research"}]';

    expect(getPlanPresentation(content, false).plan.steps).toEqual([
      { title: "检索资料", description: "查找笔记", tools: undefined },
    ]);
    expect(getPlanPresentation(content, false).invalidPlan).toBe(false);
    expect(getPlanPresentation(content, false).canStartResearch).toBe(true);
  });

  it("流式 JSON 暂无步骤时等待后续内容，结束后标记异常", () => {
    const content = '{"title":"学习计划","steps":[]';

    expect(getPlanPresentation(content, true).invalidPlan).toBe(false);
    expect(getPlanPresentation(content, false).invalidPlan).toBe(true);
    expect(getPlanPresentation(content, false).canStartResearch).toBe(false);
  });

  it("剔除无效步骤，避免空字段或 null 使计划卡崩溃", () => {
    const content = '{"steps":[null,{"title":42}, {"title":"有效步骤"}]}';

    expect(getPlanPresentation(content, false).plan.steps).toEqual([]);
    expect(getPlanPresentation(content, false).canStartResearch).toBe(false);
    expect(getPlanPresentation(content, false).invalidPlan).toBe(true);
  });

  it("JSON 形态的无步骤回答也不透出未经核实的标题和说明", () => {
    const content = '{"title":"错误事实","thought":"未经核查的断言"}';

    expect(getPlanPresentation(content, false)).toEqual({
      plan: { steps: [] },
      invalidPlan: true,
      canStartResearch: false,
    });
  });

  it("完整计划末尾混入非 JSON 内容时不开放开始研究", () => {
    const content =
      '{"steps":[{"title":"检索","description":"查资料","need_search":true}]} 后续文本';

    expect(getPlanPresentation(content, false)).toEqual({
      plan: { steps: [] },
      invalidPlan: true,
      canStartResearch: false,
    });
  });

  it("前置说明后只有一个完整 JSON 代码块时展示计划", () => {
    const content = `这是规划阶段的说明，尚未检索资料。\n\n\`\`\`json
${JSON.stringify({
  locale: "zh-CN",
  has_enough_context: false,
  thought: "先核对所选资料，找不到就说明缺失。",
  title: "授课老师信息核查计划",
  steps: [
    {
      need_search: true,
      title: "检索授课老师",
      description: "仅在所选资料中检索教师姓名和职务。",
      step_type: "research",
    },
    {
      need_search: false,
      title: "整理结果",
      description: "找到则引用原文，否则说明资料未提供。",
      step_type: "analysis",
    },
  ],
})}
\`\`\``;

    const result = getPlanPresentation(content, false);
    expect(result.canStartResearch).toBe(true);
    expect(result.invalidPlan).toBe(false);
    expect(result.plan.title).toBe("授课老师信息核查计划");
    expect(result.plan.steps).toHaveLength(2);
    expect(JSON.stringify(result)).not.toContain("这是规划阶段的说明");
  });

  it("多个代码块或代码块之后还有正文时不开放开始研究", () => {
    const plan =
      '{"steps":[{"title":"检索","description":"查资料","need_search":true,"step_type":"research"}]}';

    for (const content of [
      `说明\n\`\`\`json\n${plan}\n\`\`\`\n补充结论`,
      `说明\n\`\`\`json\n${plan}\n\`\`\`\n\`\`\`json\n${plan}\n\`\`\``,
      `说明\n\`\`\`json\n${plan}`,
    ]) {
      expect(getPlanPresentation(content, false).canStartResearch).toBe(false);
      expect(getPlanPresentation(content, false).invalidPlan).toBe(true);
    }
  });

  it("步骤缺少后端必需的 step_type 时不开放开始研究", () => {
    const content =
      '{"steps":[{"title":"检索","description":"查资料","need_search":true}]}';
    expect(getPlanPresentation(content, false).canStartResearch).toBe(false);
  });
});
