// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Database, FileText, Upload } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import { useConfig } from "~/core/api/hooks";
import {
  getRAGUploadJob,
  listRAGResources,
  startRAGUpload,
  type RAGUploadJob,
} from "~/core/api/rag";
import type { Resource } from "~/core/messages";
import {
  getResourceDisplayName,
  getResourceTypeLabel,
} from "~/core/rag-resource";
import { cn } from "~/lib/utils";

import type { Tab } from "./types";

const PENDING_UPLOAD_KEY = "deerflow.rag.pending-upload";

export const RAGTab: Tab = () => {
  const t = useTranslations("settings.rag");
  const [resources, setResources] = useState<Resource[]>([]);
  const [uploading, setUploading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [job, setJob] = useState<RAGUploadJob | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { config, loading: configLoading } = useConfig();
  const ragEnabled = Boolean(config.rag.provider);
  const processing = job?.status === "queued" || job?.status === "processing";
  const busy = uploading || processing;

  const fetchResources = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setResources(await listRAGResources());
    } catch (error) {
      console.error("Failed to fetch resources:", error);
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!configLoading && ragEnabled) void fetchResources();
  }, [configLoading, fetchResources, ragEnabled]);

  useEffect(() => {
    // 设置弹窗关闭或页面刷新后，继续查询上一次尚未完成的入库任务。
    const stored = window.localStorage.getItem(PENDING_UPLOAD_KEY);
    if (!stored) return;

    try {
      const pending = JSON.parse(stored) as RAGUploadJob;
      if (pending.task_id && pending.filename) setJob(pending);
      else window.localStorage.removeItem(PENDING_UPLOAD_KEY);
    } catch {
      window.localStorage.removeItem(PENDING_UPLOAD_KEY);
    }
  }, []);

  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "processing"))
      return;

    let cancelled = false;
    // 单次轮询结束后再更新状态，避免大文件处理时积压并发请求。
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const latest = await getRAGUploadJob(job.task_id);
          if (cancelled) return;

          setJob(latest);
          if (latest.status === "completed") {
            window.localStorage.removeItem(PENDING_UPLOAD_KEY);
            toast.success(t("uploadSuccess"));
            void fetchResources();
          } else if (latest.status === "failed") {
            window.localStorage.removeItem(PENDING_UPLOAD_KEY);
            toast.error(latest.error ?? t("uploadFailed"));
          }
        } catch (error) {
          if (cancelled) return;
          const message =
            error instanceof Error ? error.message : t("uploadFailed");
          window.localStorage.removeItem(PENDING_UPLOAD_KEY);
          setJob({ ...job, status: "failed", error: message });
          toast.error(message);
        }
      })();
    }, 1500);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [fetchResources, job, t]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (file.size === 0) {
      toast.error(t("emptyFile"));
      event.target.value = "";
      return;
    }

    setUploading(true);
    try {
      const pending = await startRAGUpload(file);
      window.localStorage.setItem(PENDING_UPLOAD_KEY, JSON.stringify(pending));
      setJob(pending);
    } catch (error) {
      console.error("Upload error:", error);
      toast.error(error instanceof Error ? error.message : t("uploadFailed"));
    } finally {
      setUploading(false);
      // 允许用户修正文件后重新选择同名文件。
      event.target.value = "";
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <header>
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-medium">{t("title")}</h1>
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt,.pdf,.docx"
              className="sr-only"
              onChange={handleUpload}
              disabled={busy || !ragEnabled}
              aria-label={t("upload")}
            />
            <Button
              disabled={busy || !ragEnabled}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="mr-2 h-4 w-4" />
              {busy ? t("uploading") : t("upload")}
            </Button>
          </div>
        </div>
        <div className={cn("text-muted-foreground text-sm")}>
          {t("description")}
        </div>
      </header>
      {!configLoading && !ragEnabled && (
        <p className="text-muted-foreground rounded-md border px-4 py-3 text-sm">
          {t("providerRequired")}
        </p>
      )}
      {job && (
        <div className="rounded-md border px-4 py-3 text-sm" aria-live="polite">
          <div className="flex items-center justify-between gap-3">
            <span className="truncate font-medium" title={job.filename}>
              {job.filename}
            </span>
            <span className="text-muted-foreground shrink-0">
              {t(`status.${job.status}`)}
            </span>
          </div>
          {processing && (
            <div
              className="bg-muted mt-2 h-2 overflow-hidden rounded-full"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={job.progress}
            >
              <div
                className="bg-primary h-full transition-[width]"
                style={{
                  width: `${Math.min(100, Math.max(0, job.progress))}%`,
                }}
              />
            </div>
          )}
          {job.status === "failed" && job.error && (
            <p className="text-destructive mt-2">{job.error}</p>
          )}
        </div>
      )}
      <main>
        {loading ? (
          <div className="flex items-center justify-center p-8 text-sm text-gray-500">
            {t("loading")}
          </div>
        ) : loadError ? (
          <p className="text-destructive p-8 text-center text-sm">
            {t("loadFailed")}
          </p>
        ) : resources.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed p-8 text-center text-gray-500">
            <Database className="h-8 w-8 opacity-50" />
            <p>{t("noResources")}</p>
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {resources.map((resource) => (
              <li
                key={resource.uri}
                className={cn(
                  "bg-card flex items-start gap-3 rounded-lg border p-3",
                )}
              >
                <div className={cn("bg-primary/10 rounded p-2")}>
                  <FileText className="text-primary h-5 w-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2">
                    <h3
                      className="truncate font-medium"
                      title={getResourceDisplayName(resource)}
                    >
                      {getResourceDisplayName(resource)}
                    </h3>
                    {getResourceTypeLabel(resource) && (
                      <span className="text-muted-foreground bg-muted shrink-0 rounded px-1.5 py-0.5 text-xs">
                        {getResourceTypeLabel(resource)}
                      </span>
                    )}
                  </div>
                  <div
                    className={cn(
                      "text-muted-foreground flex items-center gap-2 text-xs",
                    )}
                  >
                    <span
                      className="max-w-[300px] truncate"
                      title={resource.uri}
                    >
                      {resource.uri}
                    </span>
                    {resource.description && (
                      <>
                        <span>•</span>
                        <span className="truncate">{resource.description}</span>
                      </>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
};

RAGTab.icon = Database;
RAGTab.displayName = "Resources";
