// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { useEffect, useMemo } from "react";

import { initializeConversationHistory, useStore } from "~/core/store";
import { cn } from "~/lib/utils";

import { HistorySidebar } from "./components/history-sidebar";
import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";

export default function Main() {
  useEffect(() => {
    void initializeConversationHistory();
  }, []);
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = useMemo(
    () => openResearchId !== null,
    [openResearchId],
  );
  return (
    <div
      className={cn(
        "flex h-full w-full min-w-0 justify-center-safe overflow-x-clip px-4 pt-24 pb-4",
        doubleColumnMode && "gap-8 max-xl:flex-col max-xl:gap-4",
      )}
    >
      <HistorySidebar />
      <MessagesBlock
        className={cn(
          "min-h-0 min-w-0 transition-all duration-300 ease-out",
          !doubleColumnMode && "w-full max-w-[768px]",
          doubleColumnMode &&
            "w-full max-w-[538px] shrink-0 max-xl:max-w-none max-xl:flex-1 max-xl:basis-0",
        )}
      />
      <ResearchBlock
        className={cn(
          "min-h-0 max-w-[960px] min-w-0 flex-1 pb-4 transition-all duration-300 ease-out max-xl:max-w-none max-xl:basis-0 max-xl:pb-0",
          !doubleColumnMode && "hidden",
        )}
        researchId={openResearchId}
      />
    </div>
  );
}
