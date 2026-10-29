// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useRef } from "react";

import { CitationList } from "~/components/deer-flow/citation";
import { LoadingAnimation } from "~/components/deer-flow/loading-animation";
import { Markdown } from "~/components/deer-flow/markdown";
import ReportEditor from "~/components/editor";
import { auditReportEvidence } from "~/core/evidence/audit";
import { useReplay } from "~/core/replay";
import { useCitations, useMessage, useStore } from "~/core/store";
import { cn } from "~/lib/utils";

export function ResearchReportBlock({
  className,
  researchId,
  messageId,
  editing,
}: {
  className?: string;
  researchId: string;
  messageId: string;
  editing: boolean;
}) {
  const message = useMessage(messageId);
  const citations = useCitations(researchId);
  const tEvidence = useTranslations("chat.evidence");
  const evidence = useMemo(
    () => auditReportEvidence(message?.content ?? "", citations),
    [message?.content, citations],
  );
  const { isReplay } = useReplay();
  const handleMarkdownChange = useCallback(
    (markdown: string) => {
      if (message) {
        message.content = markdown;
        useStore.setState({
          messages: new Map(useStore.getState().messages).set(
            message.id,
            message,
          ),
        });
      }
    },
    [message],
  );
  const contentRef = useRef<HTMLDivElement>(null);
  const isCompleted = message?.isStreaming === false && message?.content !== "";
  // TODO: scroll to top when completed, but it's not working
  // useEffect(() => {
  //   if (isCompleted && contentRef.current) {
  //     setTimeout(() => {
  //       contentRef
  //         .current!.closest("[data-radix-scroll-area-viewport]")
  //         ?.scrollTo({
  //           top: 0,
  //           behavior: "smooth",
  //         });
  //     }, 500);
  //   }
  // }, [isCompleted]);

  return (
    <div ref={contentRef} className={cn("w-full pt-4 pb-8", className)}>
      {!isReplay && isCompleted && editing ? (
        <ReportEditor
          content={message?.content}
          onMarkdownChange={handleMarkdownChange}
        />
      ) : (
        <>
          <Markdown animated checkLinkCredibility citations={citations}>
            {message?.content}
          </Markdown>
          {message?.isStreaming && <LoadingAnimation className="my-12" />}
        </>
      )}
      {isCompleted && (
        <section
          className="mt-8 space-y-4 border-t pt-5"
          aria-label={tEvidence("title")}
        >
          <div className="space-y-1">
            <h3 className="text-foreground text-base font-semibold">
              {tEvidence("title")}
            </h3>
            <p className="text-foreground text-sm">
              {tEvidence("coverage", {
                covered: evidence.coveredParagraphs,
                total: evidence.totalParagraphs,
                percent: evidence.coveragePercent,
              })}
            </p>
            <p className="text-muted-foreground text-xs">
              {tEvidence("coverageDisclaimer")}
            </p>
          </div>

          {(evidence.unmatchedUrls.length > 0 ||
            evidence.invalidCitationNumbers.length > 0) && (
            <div
              className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm"
              role="status"
            >
              <AlertTriangle className="mr-2 inline h-4 w-4 text-amber-600" />
              {evidence.unmatchedUrls.length > 0 && (
                <>
                  <p className="inline">
                    {tEvidence("unknownUrls", {
                      count: evidence.unmatchedUrls.length,
                    })}
                  </p>
                  <details className="mt-1 pl-6">
                    <summary className="cursor-pointer">
                      {tEvidence("unknownUrlLabel")}
                    </summary>
                    <ul className="mt-1 max-h-32 list-disc overflow-y-auto pl-5 break-all">
                      {evidence.unmatchedUrls.map((url) => (
                        <li key={url}>{url}</li>
                      ))}
                    </ul>
                  </details>
                </>
              )}
              {evidence.invalidCitationNumbers.length > 0 && (
                <p>
                  {tEvidence("invalidNumbers", {
                    count: evidence.invalidCitationNumbers.length,
                  })}{" "}
                  {tEvidence("invalidNumberLabel")}:{" "}
                  {evidence.invalidCitationNumbers.join(", ")}
                </p>
              )}
            </div>
          )}

          {citations.length > 0 ? (
            <CitationList
              citations={citations}
              title={tEvidence("sourcesTitle")}
            />
          ) : (
            <p className="text-muted-foreground rounded-lg border p-3 text-sm">
              {tEvidence("noSources")}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
