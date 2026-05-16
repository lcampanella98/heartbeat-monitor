import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import Link from 'next/link'
import './globals.css'
import { Providers } from '@/components/providers'
import { DemoBanner } from '@/components/DemoBanner'

const geistSans = Geist({
  variable: '--font-geist-sans',
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

const navItems = [
  { href: '/', label: 'Dashboard' },
  { href: '/endpoints', label: 'Endpoints' },
  { href: '/incidents', label: 'Incidents' },
  { href: '/notifications', label: 'Notifications' },
  { href: '/settings', label: 'Settings' },
]

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full`}>
      <body className="h-full flex flex-col antialiased">
        <Providers>
          <div className="flex h-full">
            {/* Sidebar */}
            <aside className="w-52 shrink-0 border-r border-border bg-sidebar flex flex-col">
              <div className="px-4 py-5 border-b border-border">
                <span className="text-sm font-semibold text-sidebar-foreground tracking-tight">
                  Heartbeat Monitor
                </span>
              </div>
              <nav className="flex-1 px-2 py-4 space-y-0.5">
                {navItems.map(({ href, label }) => (
                  <Link
                    key={href}
                    href={href}
                    className="flex items-center px-3 py-2 text-sm rounded-md text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground transition-colors"
                  >
                    {label}
                  </Link>
                ))}
              </nav>
            </aside>

            {/* Main content */}
            <div className="flex-1 flex flex-col min-w-0">
              <DemoBanner />
              <main className="flex-1 overflow-auto">{children}</main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  )
}
