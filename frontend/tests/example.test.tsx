// "Try an example": one click fills the form and runs the sample trip.
import { screen } from '@testing-library/react'
import { render } from './render'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TripForm } from '../src/components/TripForm'
import { EXAMPLE } from '../src/lib/example'
import { useUi } from '../src/store/ui'

describe('Try an example', () => {
  beforeEach(() => act(() => useUi.getState().setUnits('imperial')))

  it('fills the form and submits the sample trip in pounds and miles', async () => {
    const onSubmit = vi.fn()
    render(<TripForm busy={false} onSubmit={onSubmit} />)
    await userEvent.click(screen.getByRole('button', { name: /Try an example/ }))

    expect(onSubmit).toHaveBeenCalledTimes(1)
    const req = onSubmit.mock.calls[0][0]
    expect(req).toMatchObject({
      origin: EXAMPLE.origin,
      destination: EXAMPLE.destination,
      load_weight_lb: 42000,
      interval_mi: 25,
    })
    // Departs at the next whole hour, in the future.
    const dep = new Date(req.departure_time).getTime()
    expect(dep).toBeGreaterThan(Date.now())
    expect(dep - Date.now()).toBeLessThanOrEqual(3_600_000)

    expect(screen.getByLabelText('Origin')).toHaveValue(EXAMPLE.origin)
    expect(screen.getByLabelText('Destination')).toHaveValue(EXAMPLE.destination)
    expect(screen.getByLabelText('Load weight (lb)')).toHaveValue(42000)
  })

  it('still sends pounds when the display is metric', async () => {
    act(() => useUi.getState().setUnits('metric'))
    const onSubmit = vi.fn()
    render(<TripForm busy={false} onSubmit={onSubmit} />)
    await userEvent.click(screen.getByRole('button', { name: /Try an example/ }))
    expect(onSubmit.mock.calls[0][0].load_weight_lb).toBe(42000)
    expect(screen.getByLabelText('Load weight (kg)')).toHaveValue(19051)
  })

  it('is disabled while an analysis is running', () => {
    render(<TripForm busy onSubmit={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Try an example/ })).toBeDisabled()
  })
})
