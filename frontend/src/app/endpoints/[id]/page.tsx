import EndpointDetailClient from './EndpointDetailClient'

export function generateStaticParams() {
  return [{ id: '__placeholder__' }]
}

export default function Page() {
  return <EndpointDetailClient />
}
