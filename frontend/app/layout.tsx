import type { Metadata, Viewport } from "next";
import { JetBrains_Mono, Space_Grotesk } from "next/font/google";
import { Footer } from "@/components/Footer";
import { RadarProvider } from "@/components/RadarProvider";
import "./globals.css";

const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-grotesk", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jbmono", display: "swap" });

export const metadata: Metadata = {
  title: "New Token Radar — live new tokens across chains",
  description:
    "Real-time feed of brand-new tokens launching on Solana (Pump.fun), Ethereum, BNB Chain, Base, Arbitrum, Polygon, Optimism and Avalanche.",
};

export const viewport: Viewport = {
  themeColor: "#06080b",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${grotesk.variable} ${mono.variable}`}>
      <body className="font-sans">
        {/* One live connection shared by every page */}
        <RadarProvider>
          <div className="relative flex min-h-dvh flex-col">
            {children}
            <Footer />
          </div>
        </RadarProvider>
      </body>
    </html>
  );
}
