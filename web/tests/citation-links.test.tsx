import { render, screen } from "@testing-library/react";

import { CitationList } from "../src/components/deer-flow/citation";
import type { Citation } from "../src/core/messages/types";

const citations: Citation[] = [
  {
    url: "qdrant://documents/paper#page=3",
    title: "上传论文",
    source_type: "local_document",
    page_number: 3,
  },
  {
    url: "javascript:alert(1)",
    title: "不安全地址",
    source_type: "web_search",
  },
  {
    url: "https://example.org/article",
    title: "真实网页",
    source_type: "web_search",
  },
];

describe("CitationList", () => {
  it("只让 HTTP 来源可点击，并显示本地资料页码", () => {
    render(<CitationList citations={citations} />);

    expect(screen.getByText("上传论文")).toBeTruthy();
    expect(screen.getByText("第 3 页")).toBeTruthy();
    expect(screen.getByText("不安全地址")).toBeTruthy();

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0]?.getAttribute("href")).toBe("https://example.org/article");
  });
});
