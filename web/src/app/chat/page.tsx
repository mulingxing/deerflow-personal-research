// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { GithubOutlined } from "@ant-design/icons";
import { Presentation } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { Suspense } from "react";

import { LanguageSwitcher } from "~/components/deer-flow/language-switcher";
import { Button } from "~/components/ui/button";

import { Logo } from "../../components/deer-flow/logo";
import { ThemeToggle } from "../../components/deer-flow/theme-toggle";
import { Tooltip } from "../../components/deer-flow/tooltip";
import { SettingsDialog } from "../settings/dialogs/settings-dialog";

const Main = dynamic(() => import("./main"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full w-full items-center justify-center">
      Loading DeerFlow...
    </div>
  ),
});

export default function HomePage() {
  const t = useTranslations("chat.page");
  const tPpt = useTranslations("ppt");

  return (
    <div className="flex h-screen w-screen justify-center overscroll-none">
      <header className="fixed top-0 left-0 flex h-12 w-full items-center justify-between px-4">
        <Logo />
        <div className="flex items-center">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/ppt" aria-label={tPpt("title")}>
              <Presentation className="h-4 w-4" />
              <span className="hidden sm:inline">{tPpt("title")}</span>
            </Link>
          </Button>
          <LanguageSwitcher />
          <Tooltip title={t("starOnGitHub")}>
            <Button variant="ghost" size="icon" asChild>
              <Link
                href="https://github.com/bytedance/deer-flow"
                target="_blank"
              >
                <GithubOutlined />
              </Link>
            </Button>
          </Tooltip>
          <ThemeToggle />
          <Suspense>
            <SettingsDialog />
          </Suspense>
        </div>
      </header>
      <Main />
    </div>
  );
}
