import type { PPTTheme } from "~/core/ppt";

import { resolveServiceURL } from "./resolve-service-url";

export async function generatePPT({
  content,
  locale,
  theme,
}: {
  content: string;
  locale: string;
  theme: PPTTheme;
}): Promise<Blob> {
  const response = await fetch(resolveServiceURL("ppt/generate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, locale, theme }),
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ?? detail;
    } catch {
      // 后端也可能返回纯文本错误；保留 HTTP 状态提示。
    }
    throw new Error(detail);
  }

  return response.blob();
}
