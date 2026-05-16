import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'
import { Providers } from '@/components/providers'
import { DemoBanner } from '@/components/DemoBanner'
import { NavLinks } from '@/components/NavLinks'

const geistSans = Geist({
  variable: '--font-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'Heartbeat Monitor',
  description: 'Uptime monitor and status page',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark h-full`}
    >
      <body className="h-full flex flex-col antialiased">
        <Providers>
          <div className="flex h-full">
            {/* Sidebar */}
            <aside className="w-52 shrink-0 border-r border-sidebar-border bg-sidebar flex flex-col">
              <div className="px-4 py-5 border-b border-sidebar-border">
                <span className="text-sm font-semibold text-sidebar-foreground tracking-tight">
                  Heartbeat Monitor
                </span>
              </div>
              <NavLinks />
            </aside>

            {/* Main content */}
            <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
              <DemoBanner />
              <main className="flex-1 overflow-auto">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  )
}
