import {
  getResourceDisplayName,
  getResourceTypeLabel,
} from "../src/core/rag-resource";

describe("资料名称展示", () => {
  it("同名 PDF 和 Word 在选择列表中可以区分", () => {
    const pdf = {
      uri: "qdrant://documents/pdf",
      title: "Agent面试问答",
      filename: "Agent面试问答.pdf",
    };
    const word = {
      uri: "qdrant://documents/word",
      title: "Agent面试问答",
      filename: "Agent面试问答.docx",
    };

    expect(getResourceDisplayName(pdf)).toBe("Agent面试问答.pdf");
    expect(getResourceTypeLabel(pdf)).toBe("PDF");
    expect(getResourceDisplayName(word)).toBe("Agent面试问答.docx");
    expect(getResourceTypeLabel(word)).toBe("Word");
  });

  it("没有原文件名的旧资料继续显示标题", () => {
    const resource = {
      uri: "rag://example",
      title: "示例资料",
    };

    expect(getResourceDisplayName(resource)).toBe("示例资料");
    expect(getResourceTypeLabel(resource)).toBeNull();
  });
});
