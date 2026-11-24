import { useTranslations } from "next-intl";
import LegalText from "@/components/legal/LegalText";
import { legalMetadata } from "../_legalMetadata";

export const generateMetadata = legalMetadata;

export default function DatenschutzPage() {
  const t = useTranslations("privacy");
  return (
    <div className="max-w-4xl mx-auto px-4 py-10">
        <div className="bg-background rounded-xl shadow-sm border border-border-soft p-8">
          <h1 className="text-2xl font-bold mb-6">{t("title")}</h1>

          <LegalText kind="privacy" />
        </div>
    </div>
  );
}
