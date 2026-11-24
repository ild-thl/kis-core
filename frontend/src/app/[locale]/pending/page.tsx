"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import Header from "@/components/layout/Header";
import Mascot from "@/components/ui/Mascot";
import { useMascotPref } from "@/hooks/useMascotPref";
import { useLegal } from "@/lib/legal";

export default function TestphasePage() {
  const t = useTranslations("pending");
  const contactEmail = useLegal()?.contactEmail ?? "";
  const { variant: mascotVariant } = useMascotPref();

  return (
    <>
      <Header />
      <div className="flex items-center justify-center min-h-[70vh] px-4">
        <div className="w-full max-w-lg">
          <div className="bg-background rounded-xl shadow-sm border border-border-soft p-8 text-center">
            <div className="flex justify-center mb-4">
              <Mascot variant={mascotVariant} size={140} state="wave" />
            </div>

            <h1 className="text-xl font-bold mb-2">
              {t("title")}
            </h1>

            <p className="text-foreground-soft mb-4">
              {t("body1")}
            </p>

            <p className="text-foreground-soft mb-6">
              {t("body2")}
            </p>

            {contactEmail && (
              <a
                href={`mailto:${contactEmail}`}
                className="inline-block px-4 py-2 btn-primary text-sm font-medium rounded-md  transition-colors mb-6"
              >
                {contactEmail}
              </a>
            )}

            <div>
              <Link
                href="/login"
                className="text-sm text-kb hover:underline"
              >
                {t("backToLogin")}
              </Link>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
