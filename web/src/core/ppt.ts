export const PPT_DRAFT_STORAGE_KEY = "deerflow.ppt.draft";

export const PPT_THEME_IDS = [
  "default",
  "gaia",
  "uncover",
  "midnight",
  "paper",
] as const;

export type PPTTheme = (typeof PPT_THEME_IDS)[number];

// 页面语言为 zh/en，PPT 提示词文件按 zh_CN/en_US 查找。
export function toPPTPromptLocale(uiLocale: string): "zh-CN" | "en-US" {
  return uiLocale === "zh" ? "zh-CN" : "en-US";
}
