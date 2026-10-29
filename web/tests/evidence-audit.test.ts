import {
  auditReportEvidence,
  isWebSourceUrl,
} from "../src/core/evidence/audit";
import type { Citation } from "../src/core/messages/types";

const webCitation: Citation = {
  url: "https://example.org/research",
  title: "研究资料",
  source_type: "web_search",
};

describe("auditReportEvidence", () => {
  it("只统计正文段落，排除参考文献并计算有效编号覆盖", () => {
    const report = `# 研究报告

## 分析

这是第一段研究分析，内容超过三十个字符，并且明确标注了检索所得的来源。[[1]](#ref-1)

这是第二段研究分析，同样超过三十个字符，但是尚未添加来源编号，需要保守地计为未覆盖。

## 参考文献

[[1]](#citation-target-1) **[研究资料](https://example.org/research)**`;

    expect(auditReportEvidence(report, [webCitation])).toEqual({
      unmatchedUrls: [],
      invalidCitationNumbers: [],
      coveredParagraphs: 1,
      totalParagraphs: 2,
      coveragePercent: 50,
    });
  });

  it("指出未匹配的来源链接和越界编号，但不推断内容真伪", () => {
    const report =
      "这是一段有实际内容的分析文字，长度足以成为正文段落。[[3]](#ref-3) [其他来源](https://unknown.example/article)";
    const result = auditReportEvidence(report, [webCitation]);

    expect(result.unmatchedUrls).toEqual(["https://unknown.example/article"]);
    expect(result.invalidCitationNumbers).toEqual([3]);
    expect(result.coveredParagraphs).toBe(0);
    expect(result.totalParagraphs).toBe(1);
  });

  it("将本地资料的页码片段归于同一文件，并忽略图片和代码中的链接", () => {
    const localCitation: Citation = {
      url: "qdrant://documents/local-id#page=2",
      title: "上传论文",
      source_type: "local_document",
      page_number: 2,
    };
    const report = `这段分析引用了所选论文的第二页，文字长度满足正文统计要求。[[1]](#ref-1) [上传论文](qdrant://documents/local-id)

![示意图](https://images.example/not-a-source.png)

\`\`\`text
https://code.example/not-a-source
\`\`\``;
    const result = auditReportEvidence(report, [localCitation]);

    expect(result.unmatchedUrls).toEqual([]);
    expect(result.coveredParagraphs).toBe(1);
    expect(result.totalParagraphs).toBe(1);
  });

  it("只有 HTTP 和 HTTPS 可以成为可点击的网页来源", () => {
    expect(isWebSourceUrl("https://example.org/x")).toBe(true);
    expect(isWebSourceUrl("http://example.org/x")).toBe(true);
    expect(isWebSourceUrl("javascript:alert(1)")).toBe(false);
    expect(isWebSourceUrl("file:///private.txt")).toBe(false);
    expect(isWebSourceUrl("qdrant://documents/local-id")).toBe(false);
  });

  it("保留网页路径内成对括号，不把 Markdown 的右括号算进 URL", () => {
    const source: Citation = {
      url: "https://example.org/wiki/Method_(research)",
      title: "研究方法",
    };
    const report =
      "这段研究方法说明包含足够长的文字，并且标出了网页来源。[[1]](#ref-1) [方法](https://example.org/wiki/Method_(research))";

    expect(auditReportEvidence(report, [source]).unmatchedUrls).toEqual([]);
  });
});
