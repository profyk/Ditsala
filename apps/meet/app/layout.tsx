import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";

// A JS import, not a CSS @import — this package's export map doesn't
// expose a "style" condition for its root path, which is what a plain
// `@import "@livekit/components-styles";` in globals.css needs; Next's
// bundler resolves a package import from a .tsx file differently and
// this works.
import "@livekit/components-styles";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces" });

export const metadata: Metadata = {
  title: "Ditsala Conference",
  description: "Meet the world without language barriers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
