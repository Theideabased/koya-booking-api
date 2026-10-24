import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Koya Clinic | Book an appointment",
  description: "Find an available clinic appointment and reserve it in minutes.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
