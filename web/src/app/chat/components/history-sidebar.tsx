"use client";

import { History, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "~/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "~/components/ui/sheet";
import {
  createConversation,
  openConversation,
  recoverStoppedConversation,
  refreshConversations,
  removeConversation,
  useStore,
} from "~/core/store";
import { cn } from "~/lib/utils";

export function HistorySidebar() {
  const t = useTranslations("chat.history");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const conversations = useStore((state) => state.conversations);
  const conversationId = useStore((state) => state.conversationId);
  const responding = useStore((state) => state.responding);
  const switching = useStore((state) => state.conversationSwitching);
  const sendStarting = useStore((state) => state.sendStarting);
  const remoteRunning = useStore((state) => state.remoteRunning);
  const localStatus = useStore((state) => state.conversationStatus);
  const loading = useStore((state) => state.historyLoading);
  const error = useStore((state) => state.historyError);

  const runAction = async (action: () => Promise<void>, close = false) => {
    setBusy(true);
    try {
      await action();
      if (close) setOpen(false);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : t("actionFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="fixed top-14 left-4 z-40 rounded-full shadow-sm"
          aria-label={t("title")}
        >
          <History className="size-4" />
          {t("title")}
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-[340px] max-w-[90vw] gap-0">
        <SheetHeader className="pr-12">
          <SheetTitle>{t("title")}</SheetTitle>
          <SheetDescription>{t("description")}</SheetDescription>
        </SheetHeader>
        <div className="flex gap-2 px-4 pb-4">
          <Button
            size="sm"
            disabled={busy || responding || switching || sendStarting}
            onClick={() => void runAction(createConversation, true)}
          >
            <Plus className="size-4" />
            {t("newConversation")}
          </Button>
          <Button
            size="icon"
            variant="outline"
            disabled={busy || responding || switching || sendStarting}
            onClick={() => void runAction(refreshConversations)}
            aria-label={t("refresh")}
          >
            <RefreshCw className="size-4" />
          </Button>
        </div>
        {remoteRunning && (
          <div className="px-4 pb-3">
            <Button
              size="sm"
              variant="outline"
              disabled={busy || switching || sendStarting}
              onClick={() => {
                if (window.confirm(t("recoverConfirm"))) {
                  void runAction(recoverStoppedConversation);
                }
              }}
            >
              {t("recoverStopped")}
            </Button>
          </div>
        )}
        {responding && (
          <p className="text-muted-foreground px-4 pb-3 text-xs">
            {t("finishCurrent")}
          </p>
        )}
        {error && <p className="text-destructive px-4 pb-3 text-xs">{error}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {loading ? (
            <p className="text-muted-foreground px-2 py-3 text-sm">
              {t("loading")}
            </p>
          ) : conversations.length === 0 ? (
            <p className="text-muted-foreground px-2 py-3 text-sm">
              {t("empty")}
            </p>
          ) : (
            <ul className="space-y-1">
              {conversations.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "group flex items-center gap-1 rounded-lg",
                    item.id === conversationId && "bg-accent",
                  )}
                >
                  <button
                    type="button"
                    className="hover:bg-accent min-w-0 flex-1 rounded-lg px-3 py-2 text-left"
                    disabled={busy || responding || switching || sendStarting}
                    onClick={() =>
                      void runAction(() => openConversation(item.id), true)
                    }
                  >
                    <span className="block truncate text-sm font-medium">
                      {item.title}
                    </span>
                    <span className="text-muted-foreground block text-xs">
                      {item.id === conversationId && remoteRunning
                        ? t("runningElsewhere")
                        : item.id === conversationId &&
                            localStatus === "needs_retry"
                          ? t("needsRetry")
                          : item.status === "needs_retry"
                            ? t("needsRetry")
                            : new Date(item.updated_at).toLocaleString()}
                    </span>
                  </button>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="mr-1 size-8 shrink-0"
                    disabled={
                      busy ||
                      responding ||
                      switching ||
                      sendStarting ||
                      item.status === "running"
                    }
                    aria-label={t("delete")}
                    onClick={() => {
                      if (window.confirm(t("deleteConfirm"))) {
                        void runAction(() => removeConversation(item.id));
                      }
                    }}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
