import IncidentDetailClient from './IncidentDetailClient'

export function generateStaticParams() {
  return [{ id: '__placeholder__' }]
}

export default function Page() {
  return <IncidentDetailClient />
}
