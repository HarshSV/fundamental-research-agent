import type { Metadata } from "next";
import { Manrope, Poppins } from "next/font/google";
import "./globals.css";

const poppins = Poppins({
  variable: "--font-poppins",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

// the brand name only: a clean modern grotesque that reads as a financial product without being formal
const manrope = Manrope({
  variable: "--font-brand",
  subsets: ["latin"],
  weight: ["700", "800"],
});

export const metadata: Metadata = {
  title: "NAVRIST AI",
  description: "Advanced stock screening powered by NSE Market data.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // suppressHydrationWarning: the inline script below may add the `light` class before React hydrates.
    <html lang="en" className={`${poppins.variable} ${manrope.variable} h-full antialiased`} suppressHydrationWarning>
      <head>
        {/* Apply the saved theme before first paint so a light-mode user never sees a dark flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `var d=false;try{d=localStorage.getItem('navrist_theme')==='dark'}catch(e){}if(!d)document.documentElement.classList.add('light')`,
          }}
        />
      </head>
      <body className="ml min-h-full flex flex-col">{children}</body>
    </html>
  );
}
