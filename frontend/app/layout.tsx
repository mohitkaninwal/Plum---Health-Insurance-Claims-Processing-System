import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Plum Claims Ops",
  description: "Explainable health insurance claims processing review UI"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

