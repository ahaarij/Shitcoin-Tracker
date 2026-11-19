import type { Metadata } from "next";
import { RunnersPage } from "@/components/RunnersPage";

export const metadata: Metadata = {
  title: "Runners — New Token Radar",
  description: "Brand-new tokens whose market cap jumped 200%+ within 30 minutes of launch, with full details.",
};

export default function Page() {
  return <RunnersPage />;
}
