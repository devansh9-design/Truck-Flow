// render() with a fresh TanStack Query client, for components that read queries.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render as rtlRender, type RenderOptions } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'

export function render(ui: ReactElement, options?: Omit<RenderOptions, 'wrapper'>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
  return rtlRender(ui, { wrapper: Wrapper, ...options })
}
