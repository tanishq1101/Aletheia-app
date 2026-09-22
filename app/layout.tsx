import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Fraunces, Source_Serif_4, Inter, JetBrains_Mono } from "next/font/google";
import Providers from "@/components/Providers";
import { THEME_BOOTSTRAP_SCRIPT } from "@/lib/theme";
import "./globals.css";

const fraunces = Fraunces({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "600", "900"],
});

const sourceSerif4 = Source_Serif_4({
  variable: "--font-reading",
  subsets: ["latin"],
  weight: ["400"],
});

const inter = Inter({
  variable: "--font-ui",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const jetBrainsMono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Aletheia",
  description: "Aletheia",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    // `suppressHydrationWarning` because the script below writes `data-theme`
    // onto this element before React hydrates. That difference is the point of
    // the script, not a bug for React to report.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${fraunces.variable} ${sourceSerif4.variable} ${inter.variable} ${jetBrainsMono.variable} h-full antialiased`}
    >
      <head>
        {/* Must run before the first paint, or a reader whose theme is light
            gets a dark flash on every navigation. */}
        <script
          dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }}
        />
      </head>
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
