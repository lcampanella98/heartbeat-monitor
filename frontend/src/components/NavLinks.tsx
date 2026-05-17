'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const navItems = [
  { href: '/', label: 'Dashboard' },
  { href: '/endpoints', label: 'Endpoints' },
  { href: '/incidents', label: 'Incidents' },
  { href: '/notifications', label: 'Notifications' },
  { href: '/settings', label: 'Settings' },
]

export function NavLinks() {
  const pathname = usePathname()

  return (
    <nav className="flex-1 px-2 py-4 space-y-0.5">
      {navItems.map(({ href, label }) => {
        const isActive = href === '/' ? pathname === '/' : pathname.startsWith(href)
        return (
          <Link
            key={href}
            href={href}
            onClick={(e) => {
              // When the pathname already matches, force a full navigation so any
              // query params (e.g. ?id=) are cleared — client-side pushState to
              // the same pathname is a no-op in static-export mode.
              if (pathname === href) {
                e.preventDefault()
                window.location.href = href
              }
            }}
            className={cn(
              'flex items-center px-3 py-2 text-sm rounded-md transition-colors',
              isActive
                ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                : 'text-sidebar-foreground/60 hover:text-sidebar-foreground hover:bg-sidebar-accent/50',
            )}
          >
            {label}
          </Link>
        )
      })}
    </nav>
  )
}
