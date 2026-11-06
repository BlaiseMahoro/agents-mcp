import type { Metadata } from "next";
import { Alegreya_Sans, IM_Fell_English, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const alegreyaSans = Alegreya_Sans({ variable: "--font-alegreya-sans", subsets: ["latin"], weight: ["400", "500", "700"] });
const fell = IM_Fell_English({ variable: "--font-fell", subsets: ["latin"], weight: "400", style: ["normal", "italic"] });
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Wizard",
  description: "Ask the Wizard: a Seer searches, a Scribe writes the spell, a Conjurer casts it.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${alegreyaSans.variable} ${fell.variable} ${jetbrains.variable} h-full antialiased`}>
      <body className="h-full">{children}</body>
    </html>
  );
}
