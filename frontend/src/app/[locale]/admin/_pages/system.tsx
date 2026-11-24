"use client";

/** System: maintenance mode, the platform-wide cards and the legal texts of this installation. */

import MaintenanceCard from "../_settings/MaintenanceCard";
import HomeNoticeCard from "../_settings/HomeNoticeCard";
import WelcomeModalCard from "../_settings/WelcomeModalCard";
import LegalCard from "../_settings/LegalCard";

export default function SystemPage() {
  return (
    <div className="space-y-4">
      <MaintenanceCard />
      <HomeNoticeCard />
      <WelcomeModalCard />
      <LegalCard />
    </div>
  );
}
