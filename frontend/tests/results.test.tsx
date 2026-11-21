import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { Results } from '../src/components/Results'
import { useUi } from '../src/store/ui'
import { ANALYZE } from './fixtures'

describe('ui store', () => {
  beforeEach(() => useUi.getState().reset(null))

  it('selecting a checkpoint also selects its route', () => {
    useUi.getState().selectCheckpoint('r2-c1')
    expect(useUi.getState().selectedRouteId).toBe('r2')
    expect(useUi.getState().selectedCheckpointId).toBe('r2-c1')
  })

  it('selecting another route clears the open checkpoint', () => {
    useUi.getState().selectCheckpoint('r0-c1')
    useUi.getState().selectRoute('r1')
    expect(useUi.getState().selectedCheckpointId).toBeNull()
  })
})

describe('Results (CORE-5 summaries)', () => {
  beforeEach(() => useUi.getState().reset(ANALYZE.recommendation.route_id))

  it('shows one card per route with the recommended route marked', () => {
    render(<Results data={ANALYZE} />)
    for (const r of ANALYZE.routes) expect(screen.getByTestId(`route-card-${r.id}`)).toBeInTheDocument()
    const rec = screen.getByTestId('route-card-r1')
    expect(within(rec).getByText(/Recommended/)).toBeInTheDocument()
    expect(within(screen.getByTestId('route-card-r0')).queryByText(/Recommended/)).toBeNull()
    expect(screen.getByTestId('recommendation')).toHaveTextContent('Take Route B')
    expect(screen.getByTestId('recommendation')).toHaveTextContent('Fewest Severe miles')
  })

  it('shows Severe, High and No Travel miles on each card', () => {
    render(<Results data={ANALYZE} />)
    const card = screen.getByTestId('route-card-r0')
    expect(within(card).getByText('Severe', { selector: 'dt' })).toBeInTheDocument()
    expect(within(card).getByText('High', { selector: 'dt' })).toBeInTheDocument()
    expect(within(card).getByText('No Travel', { selector: 'dt' })).toBeInTheDocument()
    expect(within(screen.getByTestId('route-card-r2')).getByText(/No Travel conditions/)).toBeInTheDocument()
  })

  it('lists every checkpoint of the selected route with its risk level as text', async () => {
    render(<Results data={ANALYZE} />)
    const list = screen.getByRole('heading', { name: /Route B checkpoints/ }).parentElement!.querySelector('ol')!
    expect(within(list).getAllByRole('listitem')).toHaveLength(4)
    expect(within(list).getByText('Moderate')).toBeInTheDocument()

    await userEvent.click(screen.getByTestId('route-card-r0'))
    expect(screen.getByRole('heading', { name: /Route A checkpoints/ })).toBeInTheDocument()
    expect(screen.getByText('Severe', { selector: 'ol span' })).toBeInTheDocument()
  })
})
