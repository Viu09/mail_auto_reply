import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import Toaster from "@/components/Toaster";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });

export const metadata: Metadata = {
  title: "Assistant Mail IA",
  description: "Dashboard de tri et de réponse assistée par IA",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" className={inter.variable}>
      <head>
        {/* Applique le thème sauvegardé avant le rendu (évite le flash). */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem('theme');if(t)document.documentElement.setAttribute('data-theme',t);}catch(e){}`,
          }}
        />
      </head>
      <body>
        {children}
        <Toaster />
      </body>
    </html>
  );
}
