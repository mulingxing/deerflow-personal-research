import type { Citation } from "~/core/messages";

export interface EvidenceAudit {
  unmatchedUrls: string[];
  invalidCitationNumbers: number[];
  coveredParagraphs: number;
  totalParagraphs: number;
  coveragePercent: number;
}

const SOURCE_URL_PATTERN =
  /(?:https?:\/\/|(?:rag|qdrant|milvus):\/\/)[^\s<>{}"']+/gi;
const DOUBLE_CITATION_PATTERN = /\[\[(\d+)\]\]/g;
const SINGLE_CITATION_PATTERN = /(?<!\[)\[(\d+)\](?!\])/g;
const REFERENCE_HEADING_PATTERN =
  /^(?:key citations|references|bibliography|sources|关键引文|参考文献|引用来源|资料来源|来源)$/i;

/** 只允许真实网页地址作为可点击的外部来源。 */
export function isWebSourceUrl(value: string): boolean {
  try {
    const protocol = new URL(value).protocol;
    return protocol === "http:" || protocol === "https:";
  } catch {
    return false;
  }
}

function cleanSourceUrl(value: string): string {
  let cleaned = value.trim().replace(/[.,;!?，。；！？*\]]+$/u, "");
  // Markdown 链接尾部的 ) 不是 URL；Wikipedia 路径内成对的括号要保留。
  while (
    cleaned.endsWith(")") &&
    (cleaned.match(/\)/g)?.length ?? 0) > (cleaned.match(/\(/g)?.length ?? 0)
  ) {
    cleaned = cleaned.slice(0, -1);
  }
  return cleaned;
}

function canonicalSourceUrl(value: string): string {
  const trimmed = cleanSourceUrl(value);
  try {
    const url = new URL(trimmed);
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return trimmed.split("#", 1)[0] ?? trimmed;
  }
}

function stripCodeAndImages(markdown: string): string {
  let inCodeBlock = false;
  const visibleLines = markdown.split(/\r?\n/).map((line) => {
    if (/^\s*(?:```|~~~)/.test(line)) {
      inCodeBlock = !inCodeBlock;
      return "";
    }
    return inCodeBlock ? "" : line;
  });

  return visibleLines
    .join("\n")
    .replace(/`[^`\n]*`/g, "")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "");
}

function citationNumbers(text: string): number[] {
  const numbers = new Set<number>();
  for (const match of text.matchAll(DOUBLE_CITATION_PATTERN)) {
    numbers.add(Number(match[1]));
  }
  for (const match of text.matchAll(SINGLE_CITATION_PATTERN)) {
    numbers.add(Number(match[1]));
  }
  return [...numbers].sort((left, right) => left - right);
}

function bodyParagraphs(markdown: string): string[] {
  let inReferences = false;
  const bodyLines = markdown.split("\n").map((line) => {
    const heading = /^\s*#{1,6}\s+(.+?)\s*#*\s*$/.exec(line);
    if (heading) {
      inReferences = REFERENCE_HEADING_PATTERN.test(heading[1] ?? "");
      return "";
    }
    return inReferences ? "" : line;
  });

  return bodyLines
    .join("\n")
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter((block) => {
      if (!block || /^(?:[-*+]\s|\d+[.)]\s|\||>\s*\||-{3,})/.test(block)) {
        return false;
      }
      // 短标题、表格和列表不算正文段落，避免把覆盖率算得过高。
      const plainText = block.replace(/\[[^\]]+\]\([^)]*\)/g, "").trim();
      return plainText.length >= 30;
    });
}

/** 仅核对“来源是否在检索结果中”和“段落有无编号”，不推断事实真伪。 */
export function auditReportEvidence(
  report: string,
  citations: Citation[],
): EvidenceAudit {
  const visibleReport = stripCodeAndImages(report);
  const knownUrls = new Set(
    citations
      .filter((item) => item.url)
      .map((item) => canonicalSourceUrl(item.url)),
  );
  const unmatchedUrls = new Set<string>();
  for (const match of visibleReport.matchAll(SOURCE_URL_PATTERN)) {
    const url = cleanSourceUrl(match[0]);
    if (!knownUrls.has(canonicalSourceUrl(url))) unmatchedUrls.add(url);
  }

  const invalidCitationNumbers = citationNumbers(visibleReport).filter(
    (number) => number < 1 || number > citations.length,
  );
  const paragraphs = bodyParagraphs(visibleReport);
  const coveredParagraphs = paragraphs.filter((paragraph) =>
    citationNumbers(paragraph).some(
      (number) => number > 0 && number <= citations.length,
    ),
  ).length;

  return {
    unmatchedUrls: [...unmatchedUrls],
    invalidCitationNumbers,
    coveredParagraphs,
    totalParagraphs: paragraphs.length,
    coveragePercent:
      paragraphs.length > 0
        ? Math.round((coveredParagraphs / paragraphs.length) * 100)
        : 0,
  };
}
