// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { ExternalLink, Globe, Clock, Star } from "lucide-react";
import { useMemo } from "react";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "~/components/ui/hover-card";
import { isWebSourceUrl } from "~/core/evidence/audit";
import { cn } from "~/lib/utils";
import type { Citation } from "~/core/messages";

// Re-export Citation type as CitationData for backward compatibility
export type CitationData = Citation;

interface CitationLinkProps {
  href: string;
  children: React.ReactNode;
  citations: CitationData[];
  className?: string;
  id?: string;
}

/**
 * Enhanced link component that shows citation metadata on hover.
 * Used within markdown content to provide rich citation information.
 */
export function CitationLink({
  href,
  children,
  citations,
  className,
  id,
}: CitationLinkProps) {
  // Find matching citation data for this URL
  const { citation, index } = useMemo(() => {
    if (!href || !citations) return { citation: null, index: -1 };

    // Try exact match first
    let matchIndex = citations.findIndex((c) => c.url === href);

    // If not found, try versatile comparison using normalized URLs
    if (matchIndex === -1) {
      const normalizeUrl = (url: string) => {
        try {
          return decodeURIComponent(url).trim();
        } catch {
          return url.trim();
        }
      };

      const normalizedHref = normalizeUrl(href);

      matchIndex = citations.findIndex(
        (c) => normalizeUrl(c.url) === normalizedHref,
      );
    }

    const match = matchIndex !== -1 ? citations[matchIndex] : null;

    return { citation: match, index: matchIndex };
  }, [href, citations]);

  const isLocalSource =
    citation?.source_type === "local_document" ||
    /^(?:rag|qdrant|milvus):\/\//i.test(href);
  const hasUnsafeProtocol =
    /^[a-z][a-z\d+.-]*:/i.test(href) && !isWebSourceUrl(href);

  // 本地资料和非网页协议的 URI 仅用于定位来源，不能作为网页打开。
  if (!citation) {
    if (isLocalSource || hasUnsafeProtocol) {
      return <span className={cn("text-primary", className)}>{children}</span>;
    }
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className={cn("text-primary hover:underline", className)}
      >
        {children}
      </a>
    );
  }

  const handleCitationClick = (e: React.MouseEvent) => {
    // If it's an internal-looking citation (e.g. [1])
    // or if the user clicks the citation number in the text
    // we try to scroll to the reference list at the bottom
    if (index !== -1) {
      const targetId = `ref-${index + 1}`;
      const element = document.getElementById(targetId);
      if (element) {
        e.preventDefault();
        element.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
    // If element not found or index is -1, let the default behavior (open URL) happen
  };

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        {isLocalSource || hasUnsafeProtocol ? (
          <button
            id={id}
            type="button"
            onClick={handleCitationClick}
            className={cn(
              "text-primary inline-flex cursor-pointer scroll-mt-20 items-center gap-0.5 hover:underline",
              className,
            )}
          >
            {children}
          </button>
        ) : (
          <a
            id={id}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            onClick={handleCitationClick}
            className={cn(
              "text-primary inline-flex cursor-pointer scroll-mt-20 items-center gap-0.5 hover:underline",
              className,
            )}
          >
            {children}
            <span className="text-muted-foreground ml-0.5 text-xs">
              <ExternalLink className="inline h-3 w-3" />
            </span>
          </a>
        )}
      </HoverCardTrigger>
      <HoverCardContent
        className="w-80 p-4"
        side="top"
        align="start"
        sideOffset={8}
      >
        <CitationCard citation={citation} />
      </HoverCardContent>
    </HoverCard>
  );
}

interface CitationCardProps {
  citation: CitationData;
  compact?: boolean;
}

/**
 * Card component displaying citation metadata.
 */
export function CitationCard({ citation, compact = false }: CitationCardProps) {
  const {
    title,
    url,
    description,
    domain,
    relevance_score,
    accessed_at,
    source_type,
    page_number,
    section,
  } = citation;

  // Format access date
  const formattedDate = useMemo(() => {
    if (!accessed_at) return null;
    try {
      const date = new Date(accessed_at);
      return date.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return accessed_at.slice(0, 10);
    }
  }, [accessed_at]);

  // Format relevance score as percentage
  const relevancePercent = useMemo(() => {
    if (relevance_score == null || relevance_score <= 0) return null;
    return Math.round(relevance_score * 100);
  }, [relevance_score]);

  return (
    <span className={cn("block space-y-2", compact && "space-y-1")}>
      {/* Title */}
      <span className="line-clamp-2 block text-sm leading-snug font-semibold">
        {title}
      </span>

      {/* Domain and metadata row */}
      <span className="text-muted-foreground flex items-center gap-3 text-xs">
        {domain && (
          <span className="flex items-center gap-1">
            <Globe className="h-3 w-3" />
            {domain}
          </span>
        )}
        {formattedDate && (
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {formattedDate}
          </span>
        )}
        {relevancePercent != null && (
          <span className="flex items-center gap-1">
            <Star className="h-3 w-3" />
            {relevancePercent}% match
          </span>
        )}
      </span>

      {/* Description/snippet */}
      {description && !compact && (
        <span className="text-muted-foreground line-clamp-3 block text-xs leading-relaxed">
          {description}
        </span>
      )}

      {/* Source type badge */}
      {source_type && (
        <span className="bg-secondary text-secondary-foreground inline-flex items-center rounded px-1.5 py-0.5 text-[10px]">
          {source_type === "local_document"
            ? "我的资料"
            : source_type === "web_search"
              ? "网页"
              : source_type}
        </span>
      )}

      {source_type === "local_document" && (page_number || section) && (
        <span className="text-muted-foreground ml-2 text-xs">
          {page_number ? `第 ${page_number} 页` : section}
        </span>
      )}

      {/* URL preview */}
      <span className="text-muted-foreground block truncate text-[10px] opacity-60">
        {url}
      </span>
    </span>
  );
}

interface CitationListProps {
  citations: CitationData[];
  title?: string;
  className?: string;
}

/**
 * List component for displaying all citations.
 */
export function CitationList({
  citations,
  title = "Sources",
  className,
}: CitationListProps) {
  if (!citations || citations.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-3", className)}>
      <h3 className="text-foreground text-sm font-semibold">{title}</h3>
      <div className="space-y-2">
        {citations.map((citation, index) => (
          <div
            key={citation.url || index}
            className="bg-card hover:bg-accent/50 rounded-lg border p-3 transition-colors"
          >
            <div className="flex items-start gap-3">
              <span className="bg-primary/10 text-primary flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-xs font-medium">
                {index + 1}
              </span>
              <div className="min-w-0 flex-1">
                {citation.source_type === "local_document" ||
                !isWebSourceUrl(citation.url) ? (
                  <span className="text-foreground line-clamp-1 text-sm font-medium">
                    {citation.title}
                  </span>
                ) : (
                  <a
                    href={citation.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-foreground hover:text-primary line-clamp-1 text-sm font-medium hover:underline"
                  >
                    {citation.title}
                  </a>
                )}
                {citation.domain && (
                  <p className="text-muted-foreground mt-0.5 text-xs">
                    {citation.domain}
                  </p>
                )}
                {citation.description && (
                  <p className="text-muted-foreground mt-1 line-clamp-2 text-xs">
                    {citation.description}
                  </p>
                )}
                {citation.source_type === "local_document" &&
                  (citation.page_number || citation.section) && (
                    <p className="text-muted-foreground mt-1 text-xs">
                      {citation.page_number
                        ? `第 ${citation.page_number} 页`
                        : citation.section}
                    </p>
                  )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface CitationBadgeProps {
  number: number;
  citation?: CitationData;
  onClick?: () => void;
}

/**
 * Small numbered badge for inline citations.
 */
export function CitationBadge({
  number,
  citation,
  onClick,
}: CitationBadgeProps) {
  const badge = (
    <button
      onClick={onClick}
      className="bg-primary/10 text-primary hover:bg-primary/20 ml-0.5 inline-flex h-4 w-4 cursor-pointer items-center justify-center rounded-full align-super text-[10px] font-medium transition-colors"
    >
      {number}
    </button>
  );

  if (!citation) {
    return badge;
  }

  return (
    <HoverCard openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>{badge}</HoverCardTrigger>
      <HoverCardContent className="w-72 p-3" side="top" sideOffset={4}>
        <CitationCard citation={citation} compact />
      </HoverCardContent>
    </HoverCard>
  );
}
