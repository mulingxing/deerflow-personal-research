import type { Resource } from "./messages";

export function getResourceDisplayName(resource: Resource): string {
  // 旧资料或外部知识库可能没有原文件名，此时继续显示标题。
  return resource.filename?.trim() || resource.title;
}

export function getResourceTypeLabel(resource: Resource): string | null {
  const extension = resource.filename?.split(".").pop()?.toLowerCase();

  switch (extension) {
    case "pdf":
      return "PDF";
    case "docx":
      return "Word";
    case "md":
      return "Markdown";
    case "txt":
      return "TXT";
    default:
      return null;
  }
}
