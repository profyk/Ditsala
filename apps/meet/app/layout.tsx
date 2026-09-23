import type { Metadata } from "next";
import { Fraunces, Inter } from "next/font/google";

// A JS import, not a CSS @import — this package's export map doesn't
// expose a "style" condition for its root path, which is what a plain
// `@import "@livekit/components-styles";` in globals.css needs; Next's
// bundler resolves a package import from a .tsx file differently and
// this works.
import "@livekit/components-styles";
import "./globals.css";
import { ThemeToggle } from "@/components/ThemeToggle";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-fraunces" });

export const metadata: Metadata = {
  title: "Ditsala Conference",
  description: "Meet the world without language barriers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable}`}>
      <head>
        {/* Applies the stored/system theme before paint, so there's no
            flash of the wrong theme while React hydrates. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="font-sans antialiased">
        <div className="fixed left-3 top-3 z-50">
          <ThemeToggle />
        </div>
        {children}
      </body>
    </html>
  );
}
