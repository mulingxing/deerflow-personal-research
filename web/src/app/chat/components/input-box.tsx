// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { MagicWandIcon } from "@radix-ui/react-icons";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, BookOpen, Globe2, Lightbulb, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Detective } from "~/components/deer-flow/icons/detective";
import MessageInput, {
  type MessageInputRef,
} from "~/components/deer-flow/message-input";
import { ReportStyleDialog } from "~/components/deer-flow/report-style-dialog";
import { Tooltip } from "~/components/deer-flow/tooltip";
import { BorderBeam } from "~/components/magicui/border-beam";
import { Button } from "~/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "~/components/ui/dropdown-menu";
import { enhancePrompt } from "~/core/api";
import { useConfig } from "~/core/api/hooks";
import { listRAGResources } from "~/core/api/rag";
import type { Option, Resource } from "~/core/messages";
import {
  getResourceDisplayName,
  getResourceTypeLabel,
} from "~/core/rag-resource";
import {
  setEnableDeepThinking,
  setEnableBackgroundInvestigation,
  setEnableWebSearch,
  useSettingsStore,
  useStore,
} from "~/core/store";
import { cn } from "~/lib/utils";

type ResearchMode = "web" | "local" | "hybrid";

const modeTranslationKey: Record<
  ResearchMode,
  "webOnly" | "localOnly" | "hybrid"
> = {
  web: "webOnly",
  local: "localOnly",
  hybrid: "hybrid",
};

export function InputBox({
  className,
  responding,
  feedback,
  onSend,
  onCancel,
  onRemoveFeedback,
}: {
  className?: string;
  size?: "large" | "normal";
  responding?: boolean;
  feedback?: { option: Option } | null;
  onSend?: (
    message: string,
    options?: {
      interruptFeedback?: string;
      resources?: Array<Resource>;
    },
  ) => boolean | void;
  onCancel?: () => void;
  onRemoveFeedback?: () => void;
}) {
  const t = useTranslations("chat.inputBox");
  const tHistory = useTranslations("chat.history");
  const tCommon = useTranslations("common");
  const enableDeepThinking = useSettingsStore(
    (state) => state.general.enableDeepThinking,
  );
  const backgroundInvestigation = useSettingsStore(
    (state) => state.general.enableBackgroundInvestigation,
  );
  const enableWebSearch = useSettingsStore(
    (state) => state.general.enableWebSearch,
  );
  const conversationSwitching = useStore(
    (state) => state.conversationSwitching,
  );
  const sendStarting = useStore((state) => state.sendStarting);
  const remoteRunning = useStore((state) => state.remoteRunning);
  const { config, loading } = useConfig();
  const reportStyle = useSettingsStore((state) => state.general.reportStyle);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<MessageInputRef>(null);
  const feedbackRef = useRef<HTMLDivElement>(null);

  // Enhancement state
  const [isEnhancing, setIsEnhancing] = useState(false);
  const [isEnhanceAnimating, setIsEnhanceAnimating] = useState(false);
  const [currentPrompt, setCurrentPrompt] = useState("");
  const researchMode = useStore((state) => state.researchMode);
  const selectedResources = useStore((state) => state.selectedResources);
  const setResearchMode = useStore((state) => state.setResearchMode);
  const setSelectedResources = useStore((state) => state.setSelectedResources);
  const [availableResources, setAvailableResources] = useState<Resource[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [resourceLoadFailed, setResourceLoadFailed] = useState(false);

  useEffect(() => {
    if (!enableWebSearch && researchMode !== "local") {
      setResearchMode("local");
    } else if (enableWebSearch && researchMode === "local") {
      setResearchMode(selectedResources.length > 0 ? "hybrid" : "web");
    }
  }, [
    enableWebSearch,
    researchMode,
    selectedResources.length,
    setResearchMode,
  ]);

  const loadAvailableResources = useCallback(async () => {
    if (!config.rag.provider) return;

    setResourcesLoading(true);
    setResourceLoadFailed(false);
    try {
      const latest = await listRAGResources();
      setAvailableResources(latest);
      setSelectedResources((current) =>
        current.filter((selected) =>
          latest.some((item) => item.uri === selected.uri),
        ),
      );
    } catch (error) {
      console.error("Failed to load RAG resources:", error);
      setResourceLoadFailed(true);
    } finally {
      setResourcesLoading(false);
    }
  }, [config.rag.provider, setSelectedResources]);

  const changeResearchMode = useCallback(
    (value: string) => {
      const next = value as ResearchMode;
      if ((next === "local" || next === "hybrid") && !config.rag.provider) {
        toast.error(t("providerRequired"));
        return;
      }

      setResearchMode(next);
      setEnableWebSearch(next !== "local");
      if (next === "web") setSelectedResources([]);
    },
    [config.rag.provider, setResearchMode, setSelectedResources, t],
  );

  const handleSendMessage = useCallback(
    (message: string, resources: Array<Resource>) => {
      if (responding) {
        onCancel?.();
        return true;
      }

      // 切换会话或首次加载历史时保留输入草稿，等待操作结束后再发送。
      if (conversationSwitching || sendStarting) return false;
      if (remoteRunning) {
        toast.error(tHistory("runningElsewhere"));
        return false;
      }

      if (message.trim() === "") return false;

      // 资料按钮和 @ 提及可以同时使用，按 URI 去重后再随请求发送。
      const mentionedResources = resources.filter((resource) => resource.uri);
      const mergedResources = Array.from(
        new Map(
          [...selectedResources, ...mentionedResources].map((resource) => [
            resource.uri,
            resource,
          ]),
        ).values(),
      );
      const mode =
        researchMode === "web" && mentionedResources.length > 0
          ? "hybrid"
          : researchMode;

      if (mode !== "web" && !config.rag.provider) {
        toast.error(t("providerRequired"));
        return false;
      }
      if (mode !== "web" && mergedResources.length === 0) {
        toast.error(t("resourceRequired"));
        return false;
      }

      if (mentionedResources.length > 0) setSelectedResources(mergedResources);
      if (mode !== researchMode) setResearchMode(mode);
      if (onSend) {
        const accepted = onSend(message, {
          interruptFeedback: feedback?.option.value,
          resources: mode === "web" ? [] : mergedResources,
        });
        if (accepted === false) return false;
        onRemoveFeedback?.();
        setIsEnhanceAnimating(false);
      }
      return true;
    },
    [
      responding,
      onCancel,
      onSend,
      feedback,
      onRemoveFeedback,
      selectedResources,
      setSelectedResources,
      researchMode,
      setResearchMode,
      config.rag.provider,
      conversationSwitching,
      sendStarting,
      remoteRunning,
      tHistory,
      t,
    ],
  );

  const handleEnhancePrompt = useCallback(async () => {
    if (currentPrompt.trim() === "" || isEnhancing) {
      return;
    }

    setIsEnhancing(true);
    setIsEnhanceAnimating(true);

    try {
      const enhancedPrompt = await enhancePrompt({
        prompt: currentPrompt,
        report_style: reportStyle.toUpperCase(),
      });

      // Add a small delay for better UX
      await new Promise((resolve) => setTimeout(resolve, 500));

      // Update the input with the enhanced prompt with animation
      if (inputRef.current) {
        inputRef.current.setContent(enhancedPrompt);
        setCurrentPrompt(enhancedPrompt);
      }

      // Keep animation for a bit longer to show the effect
      setTimeout(() => {
        setIsEnhanceAnimating(false);
      }, 1000);
    } catch (error) {
      console.error("Failed to enhance prompt:", error);
      setIsEnhanceAnimating(false);
      // Could add toast notification here
    } finally {
      setIsEnhancing(false);
    }
  }, [currentPrompt, isEnhancing, reportStyle]);

  return (
    <div
      className={cn(
        "bg-card relative flex min-h-42 w-full flex-col rounded-[24px] border",
        className,
      )}
      ref={containerRef}
    >
      <div className="w-full">
        <AnimatePresence>
          {feedback && (
            <motion.div
              ref={feedbackRef}
              className="bg-background border-brand absolute top-0 left-0 mt-2 ml-4 flex items-center justify-center gap-1 rounded-2xl border px-2 py-0.5"
              initial={{ opacity: 0, scale: 0 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0 }}
              transition={{ duration: 0.2, ease: "easeInOut" }}
            >
              <div className="text-brand flex h-full w-full items-center justify-center text-sm opacity-90">
                {feedback.option.text}
              </div>
              <X
                className="cursor-pointer opacity-60"
                size={16}
                onClick={onRemoveFeedback}
              />
            </motion.div>
          )}
          {isEnhanceAnimating && (
            <motion.div
              className="pointer-events-none absolute inset-0 z-20"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.3 }}
            >
              <div className="relative h-full w-full">
                {/* Sparkle effect overlay */}
                <motion.div
                  className="absolute inset-0 rounded-[24px] bg-gradient-to-r from-blue-500/10 via-purple-500/10 to-blue-500/10"
                  animate={{
                    background: [
                      "linear-gradient(45deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1))",
                      "linear-gradient(225deg, rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1))",
                      "linear-gradient(45deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1), rgba(59, 130, 246, 0.1))",
                    ],
                  }}
                  transition={{ duration: 2, repeat: Infinity }}
                />
                {/* Floating sparkles */}
                {[...Array(6)].map((_, i) => (
                  <motion.div
                    key={i}
                    className="absolute h-2 w-2 rounded-full bg-blue-400"
                    style={{
                      left: `${20 + i * 12}%`,
                      top: `${30 + (i % 2) * 40}%`,
                    }}
                    animate={{
                      y: [-10, -20, -10],
                      opacity: [0, 1, 0],
                      scale: [0.5, 1, 0.5],
                    }}
                    transition={{
                      duration: 1.5,
                      repeat: Infinity,
                      delay: i * 0.2,
                    }}
                  />
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <MessageInput
          className={cn(
            "h-24 px-4 pt-5",
            feedback && "pt-9",
            isEnhanceAnimating && "transition-all duration-500",
          )}
          ref={inputRef}
          loading={loading}
          config={config}
          onEnter={handleSendMessage}
          onChange={setCurrentPrompt}
        />
      </div>
      {/* 双栏或窄屏时工具按钮可以换行，发送按钮仍留在输入框内。 */}
      <div className="flex flex-wrap items-end gap-2 px-4 py-2">
        <div className="flex min-w-0 flex-[1_1_200px] flex-wrap items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" className="rounded-2xl">
                {researchMode === "local" ? <BookOpen /> : <Globe2 />}
                {t(modeTranslationKey[researchMode])}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              <DropdownMenuLabel>{t("researchMode")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                value={researchMode}
                onValueChange={changeResearchMode}
              >
                <DropdownMenuRadioItem value="web">
                  {t("webOnly")}
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="local">
                  {t("localOnly")}
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="hybrid">
                  {t("hybrid")}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu
            onOpenChange={(open) => {
              if (open) void loadAvailableResources();
            }}
          >
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                className="rounded-2xl"
                disabled={loading || !config.rag.provider}
                title={!config.rag.provider ? t("providerRequired") : undefined}
              >
                <BookOpen />
                {selectedResources.length > 0
                  ? t("selectedResources", { count: selectedResources.length })
                  : t("selectResources")}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="max-h-72 w-80 max-w-[calc(100vw-2rem)] overflow-y-auto"
            >
              <DropdownMenuLabel>{t("selectResources")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              {resourcesLoading ? (
                <DropdownMenuLabel>{t("selectResources")}...</DropdownMenuLabel>
              ) : resourceLoadFailed ? (
                <DropdownMenuLabel>{t("resourceLoadFailed")}</DropdownMenuLabel>
              ) : availableResources.length === 0 ? (
                <DropdownMenuLabel>
                  {t("noResourcesAvailable")}
                </DropdownMenuLabel>
              ) : (
                availableResources.map((resource) => {
                  const displayName = getResourceDisplayName(resource);
                  const typeLabel = getResourceTypeLabel(resource);

                  return (
                    <DropdownMenuCheckboxItem
                      key={resource.uri}
                      checked={selectedResources.some(
                        (selected) => selected.uri === resource.uri,
                      )}
                      onSelect={(event) => event.preventDefault()}
                      onCheckedChange={(checked) => {
                        setSelectedResources((current) =>
                          checked
                            ? [...current, resource]
                            : current.filter(
                                (item) => item.uri !== resource.uri,
                              ),
                        );
                        if (checked && researchMode === "web") {
                          changeResearchMode("hybrid");
                        }
                      }}
                      title={displayName}
                    >
                      <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                        <span className="truncate">{displayName}</span>
                        {typeLabel && (
                          <span className="text-muted-foreground bg-muted shrink-0 rounded px-1.5 py-0.5 text-xs">
                            {typeLabel}
                          </span>
                        )}
                      </span>
                    </DropdownMenuCheckboxItem>
                  );
                })
              )}
            </DropdownMenuContent>
          </DropdownMenu>

          {config?.models?.reasoning && config.models.reasoning.length > 0 && (
            <Tooltip
              className="max-w-60"
              title={
                <div>
                  <h3 className="mb-2 font-bold">
                    {t("deepThinkingTooltip.title", {
                      status: enableDeepThinking ? t("on") : t("off"),
                    })}
                  </h3>
                  <p>
                    {t("deepThinkingTooltip.description", {
                      model: config.models.reasoning[0] ?? "",
                    })}
                  </p>
                </div>
              }
            >
              <Button
                className={cn(
                  "rounded-2xl",
                  enableDeepThinking && "!border-brand !text-brand",
                )}
                variant="outline"
                onClick={() => {
                  setEnableDeepThinking(!enableDeepThinking);
                }}
              >
                <Lightbulb /> {t("deepThinking")}
              </Button>
            </Tooltip>
          )}

          <Tooltip
            className="max-w-60"
            title={
              <div>
                <h3 className="mb-2 font-bold">
                  {t("investigationTooltip.title", {
                    status: backgroundInvestigation ? t("on") : t("off"),
                  })}
                </h3>
                <p>{t("investigationTooltip.description")}</p>
              </div>
            }
          >
            <Button
              className={cn(
                "rounded-2xl",
                backgroundInvestigation && "!border-brand !text-brand",
              )}
              variant="outline"
              onClick={() =>
                setEnableBackgroundInvestigation(!backgroundInvestigation)
              }
            >
              <Detective /> {t("investigation")}
            </Button>
          </Tooltip>
          <ReportStyleDialog />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Tooltip title={t("enhancePrompt")}>
            <Button
              variant="ghost"
              size="icon"
              className={cn(
                "hover:bg-accent h-10 w-10",
                isEnhancing && "animate-pulse",
              )}
              onClick={handleEnhancePrompt}
              disabled={isEnhancing || currentPrompt.trim() === ""}
            >
              {isEnhancing ? (
                <div className="flex h-10 w-10 items-center justify-center">
                  <div className="bg-foreground h-3 w-3 animate-bounce rounded-full opacity-70" />
                </div>
              ) : (
                <MagicWandIcon className="text-brand" />
              )}
            </Button>
          </Tooltip>
          <Tooltip title={responding ? tCommon("stop") : tCommon("send")}>
            <Button
              variant="outline"
              size="icon"
              className={cn("h-10 w-10 rounded-full")}
              onClick={() => inputRef.current?.submit()}
            >
              {responding ? (
                <div className="flex h-10 w-10 items-center justify-center">
                  <div className="bg-foreground h-4 w-4 rounded-sm opacity-70" />
                </div>
              ) : (
                <ArrowUp />
              )}
            </Button>
          </Tooltip>
        </div>
      </div>
      {isEnhancing && (
        <>
          <BorderBeam
            duration={5}
            size={250}
            className="from-transparent via-red-500 to-transparent"
          />
          <BorderBeam
            duration={5}
            delay={3}
            size={250}
            className="from-transparent via-blue-500 to-transparent"
          />
        </>
      )}
    </div>
  );
}
