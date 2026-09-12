import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Fraunces, Source_Serif_4, Inter, JetBrains_Mono } from "next/font/google";
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

/** Clerk is optional at build time.
 *
 * A repository checked out without keys must still `next build` and run — the
 * sign-in page then says plainly that there are no accounts, which is what it
 * said before Clerk existed. Wrapping unconditionally makes a missing
 * publishable key a hard crash on every page instead of a degraded mode. */
const authConfigured = Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY);

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  const document = (
    <html
      lang="en"
      className={`${fraunces.variable} ${sourceSerif4.variable} ${inter.variable} ${jetBrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );

  // The dark surface tokens are the app's, not Clerk's defaults; without this
  // the modal arrives as a white rectangle in the middle of a dark page.
  return authConfigured ? (
    <ClerkProvider
      afterSignOutUrl="/sign-in"
      appearance={{
        variables: {
          colorPrimary: "#7d2027",
          colorBackground: "#14110f",
          colorInput: "#1b1815",
          colorInputForeground: "#f2ede4",
          colorForeground: "#f2ede4",
          colorMutedForeground: "#a8a096",
          borderRadius: "0.375rem",
        },
      }}
    >
      {document}
    </ClerkProvider>
  ) : (
    document
  );
}
