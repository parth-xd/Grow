import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { MouseFollower } from "./components/mouse-follower";
import { SmoothScroll } from "./components/smooth-scroll";

export const metadata: Metadata = {
  title: "Groww - Trade Smarter",
  description: "Intelligent trading with AI-powered analytics",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="cursor-none">
        <SmoothScroll />
        <MouseFollower />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
