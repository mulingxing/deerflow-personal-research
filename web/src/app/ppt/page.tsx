// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { saveAs } from "file-saver";
import { ArrowLeft, LoaderCircle, Presentation } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import { Textarea } from "~/components/ui/textarea";
import { generatePPT } from "~/core/api/ppt";
import {
  PPT_DRAFT_STORAGE_KEY,
  PPT_THEME_IDS,
  toPPTPromptLocale,
  type PPTTheme,
} from "~/core/ppt";
import { cn } from "~/lib/utils";

export default function PPTPage() {
  const t = useTranslations("ppt");
  const locale = useLocale();
  const [content, setContent] = useState("");
  const [theme, setTheme] = useState<PPTTheme>("default");
  const [isGenerating, setIsGenerating] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    try {
      const draft = window.sessionStorage.getItem(PPT_DRAFT_STORAGE_KEY);
      if (draft) setContent(draft);
    } catch {
      // 浏览器禁用临时存储时仍允许手动粘贴并生成。
    }
  }, []);

  useEffect(() => {
    if (!isGenerating) return;
    const timer = window.setInterval(() => {
      setElapsedSeconds((seconds) => seconds + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isGenerating]);

  const handleContentChange = (value: string) => {
    setContent(value);
    // 中文注释：从研究报告带来的草稿也可继续编辑，刷新页面仍能找回。
    try {
      window.sessionStorage.setItem(PPT_DRAFT_STORAGE_KEY, value);
    } catch {
      // 浏览器禁用临时存储时仍允许当前页面生成。
    }
  };

  const handleGenerate = async () => {
    if (!content.trim()) {
      toast.error(t("contentRequired"));
      return;
    }
    if (isGenerating) return;

    setIsGenerating(true);
    setElapsedSeconds(0);
    try {
      const pptx = await generatePPT({
        content: content.trim(),
        locale: toPPTPromptLocale(locale),
        theme,
      });
      const timestamp = new Date()
        .toISOString()
        .slice(0, 19)
        .replace(/[:T]/g, "-");
      saveAs(pptx, `deerflow-presentation-${timestamp}.pptx`);
      toast.success(t("generationSuccess"));
    } catch (error) {
      const detail =
        error instanceof Error ? error.message : t("generationFailed");
      toast.error(t("generationFailedWithReason", { reason: detail }));
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div className="bg-background min-h-screen">
      <header className="bg-background/90 sticky top-0 z-10 border-b backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-3">
          <Button variant="ghost" asChild>
            <Link href="/chat">
              <ArrowLeft className="h-4 w-4" />
              {t("backToChat")}
            </Link>
          </Button>
          <span className="text-muted-foreground flex items-center gap-2 text-sm">
            <Presentation className="h-4 w-4" />
            DeerFlow
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-5 py-10">
        <div className="mb-8 max-w-3xl">
          <div className="text-primary mb-2 flex items-center gap-2 text-sm font-medium">
            <Presentation className="h-4 w-4" />
            {t("eyebrow")}
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">
            {t("title")}
          </h1>
          <p className="text-muted-foreground mt-3 leading-7">
            {t("description")}
          </p>
        </div>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
          <section className="min-w-0">
            <div className="mb-3 flex items-center justify-between gap-3">
              <label htmlFor="ppt-content" className="font-medium">
                {t("contentLabel")}
              </label>
              <span className="text-muted-foreground text-xs">
                {t("characterCount", { count: content.length })}
              </span>
            </div>
            <Textarea
              id="ppt-content"
              value={content}
              onChange={(event) => handleContentChange(event.target.value)}
              placeholder={t("contentPlaceholder")}
              maxLength={200_000}
              className="min-h-80 resize-y p-4 leading-7 lg:min-h-[440px]"
              disabled={isGenerating}
            />
            <p className="text-muted-foreground mt-3 text-sm leading-6">
              {t("contentHint")}
            </p>
          </section>

          <section className="min-w-0" aria-labelledby="ppt-theme-heading">
            <h2 id="ppt-theme-heading" className="mb-1 font-medium">
              {t("themeLabel")}
            </h2>
            <p className="text-muted-foreground mb-4 text-sm">
              {t("themeHint")}
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              {PPT_THEME_IDS.map((option) => {
                const selected = theme === option;
                return (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setTheme(option)}
                    aria-pressed={selected}
                    disabled={isGenerating}
                    className={cn(
                      "bg-card focus-visible:outline-primary overflow-hidden rounded-xl border text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2",
                      selected
                        ? "border-primary ring-primary/20 ring-2"
                        : "hover:border-primary/60",
                    )}
                  >
                    <Image
                      src={`/ppt-themes/${option}.png`}
                      width={480}
                      height={270}
                      alt={t(`themes.${option}.previewAlt`)}
                      className="aspect-video w-full object-cover"
                    />
                    <span className="block px-4 py-3">
                      <span className="block font-medium">
                        {t(`themes.${option}.name`)}
                      </span>
                      <span className="text-muted-foreground mt-1 block text-xs leading-5">
                        {t(`themes.${option}.description`)}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        <div className="bg-card mt-8 flex flex-col gap-4 rounded-xl border p-5 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-medium">{t("downloadTitle")}</p>
            <p className="text-muted-foreground mt-1 text-sm">
              {t("downloadHint")}
            </p>
          </div>
          <Button
            size="lg"
            onClick={() => void handleGenerate()}
            disabled={isGenerating || !content.trim()}
            aria-busy={isGenerating}
            className="min-w-44"
          >
            {isGenerating ? (
              <>
                <LoaderCircle className="h-4 w-4 animate-spin" />
                {t("generating")}
              </>
            ) : (
              <>
                <Presentation className="h-4 w-4" />
                {t("generate")}
              </>
            )}
          </Button>
        </div>
        {isGenerating && (
          <p
            className="text-muted-foreground mt-3 text-sm"
            role="status"
            aria-live="polite"
          >
            {t("generationProgress", { seconds: elapsedSeconds })}
          </p>
        )}
      </main>
    </div>
  );
}
