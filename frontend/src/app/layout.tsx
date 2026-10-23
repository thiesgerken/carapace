import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { AppProviders } from "@/components/app-providers";
import { defaultLocale, getLocaleMessages } from "@/lib/i18n";
import "./globals.css";

const geistSans = localFont({
  src: "../fonts/geist-latin-variable.woff2",
  variable: "--font-geist-sans",
  weight: "100 900",
});
const geistMono = localFont({
  src: "../fonts/geist-mono-latin-variable.woff2",
  variable: "--font-geist-mono",
  weight: "100 900",
});
const sourceSerif = localFont({
  src: "../fonts/source-serif-4-latin-variable.woff2",
  variable: "--font-source-serif",
  weight: "200 900",
  display: "swap",
});
const defaultMessages = getLocaleMessages(defaultLocale) as {
  app?: { description?: string };
};

export const metadata: Metadata = {
  title: "carapace",
  description: defaultMessages.app?.description ?? "Security-first personal AI agent",
  manifest: "/manifest.webmanifest",
  icons: {
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#236b86",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang={defaultLocale} suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} ${sourceSerif.variable} font-sans antialiased`}
      >
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
