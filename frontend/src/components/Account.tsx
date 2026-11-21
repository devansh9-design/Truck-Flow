// Optional accounts (A6-A9): header menu, sign in / create account, account settings.
// Nothing here changes routes, risk or ranking.
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useCountries, useSignIn, useSignOut, useSignUp, useStartSession } from '../api/account'
import { ApiError, changePassword, deleteMe, updateMe } from '../api/client'
import { guessCountry } from '../lib/countries'
import { IMPERIAL_COUNTRIES, useAuth } from '../store/auth'
import { useUi } from '../store/ui'

const inputCls =
  'w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ' +
  'focus:border-sky-600 focus:outline-none focus:ring-2 focus:ring-sky-600/30 aria-[invalid=true]:border-red-500'
const primaryBtn =
  'w-full rounded-md bg-sky-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-sky-800 ' +
  'focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 disabled:cursor-wait disabled:bg-slate-400'

type Errors = Record<string, string>

function errorsOf(e: unknown): Errors {
  if (e instanceof ApiError) return { [e.field ?? 'form']: e.message }
  return { form: 'Something went wrong. Please try again.' }
}

function Field({
  id,
  label,
  error,
  children,
  hint,
}: {
  id: string
  label: string
  error?: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-slate-700">
        {label}
      </label>
      {children}
      {hint && !error && <p className="mt-1 text-[11px] text-slate-500">{hint}</p>}
      {error && (
        <p id={`${id}-err`} className="mt-1 text-xs text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}

export function CountrySelect({
  id,
  value,
  onChange,
  error,
}: {
  id: string
  value: string
  onChange: (code: string) => void
  error?: string
}) {
  const { data, isPending, isError } = useCountries()
  return (
    <select
      id={id}
      required
      className={inputCls}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={!!error}
      aria-describedby={error ? `${id}-err` : undefined}
      disabled={isPending}
    >
      <option value="">
        {isPending ? 'Loading countries…' : isError ? 'Countries unavailable' : 'Choose your country'}
      </option>
      {data?.continents.map((cont) => (
        <optgroup key={cont} label={cont}>
          {data.countries
            .filter((c) => c.continent === cont)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
        </optgroup>
      ))}
    </select>
  )
}

/** Native modal dialog: focus trap, Esc to close and a backdrop come with <dialog>. */
function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal?.()
    if (!open && d.open) d.close?.()
  }, [open])
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      onCancel={onClose}
      className="m-auto w-[min(420px,calc(100vw-24px))] rounded-xl bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-900/40"
    >
      {open && (
        <div className="max-h-[85dvh] overflow-y-auto p-5">
          <div className="mb-4 flex items-start justify-between gap-3">
            <h2 id={titleId} className="text-base font-bold">
              {title}
            </h2>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-m-1 rounded p-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50"
            >
              <span aria-hidden="true">✕</span>
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  )
}

export function AuthDialog({
  open,
  initialMode,
  onClose,
  onDone,
}: {
  open: boolean
  initialMode: 'signin' | 'signup'
  onClose: () => void
  onDone: (message: string) => void
}) {
  const [mode, setMode] = useState(initialMode)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [country, setCountry] = useState(guessCountry)
  const [errors, setErrors] = useState<Errors>({})
  const signIn = useSignIn()
  const signUp = useSignUp()
  const startSession = useStartSession()
  const busy = signIn.isPending || signUp.isPending
  const signup = mode === 'signup'

  async function submit(ev: FormEvent) {
    ev.preventDefault()
    const e: Errors = {}
    if (signup && !name.trim()) e.name = 'Enter your name.'
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) e.email = 'Enter a valid email address.'
    if (!password) e.password = 'Enter your password.'
    else if (signup && password.length < 8) e.password = 'Use at least 8 characters.'
    if (signup && !country) e.country = 'Choose your country.'
    setErrors(e)
    if (Object.keys(e).length) return
    try {
      const session = signup
        ? await signUp.mutateAsync({ name: name.trim(), email: email.trim(), password, country })
        : await signIn.mutateAsync({ email: email.trim(), password })
      // New accounts start with the units their roads use; the toggle can still change it.
      if (signup) useUi.getState().setUnits(IMPERIAL_COUNTRIES.has(session.user.country) ? 'imperial' : 'metric')
      const moved = await startSession(session)
      setPassword('')
      onDone(
        `${signup ? 'Welcome' : 'Welcome back'}, ${session.user.name}.` +
          (moved ? ` Moved ${moved} saved trip${moved === 1 ? '' : 's'} from this browser to your account.` : ''),
      )
    } catch (err) {
      setErrors(errorsOf(err))
    }
  }

  const err = (k: string) => errors[k]
  const described = (k: string) => (err(k) ? `auth-${k}-err` : undefined)

  return (
    <Modal open={open} onClose={onClose} title={signup ? 'Create your account' : 'Sign in'}>
      <div
        role="tablist"
        aria-label="Account"
        className="mb-4 grid grid-cols-2 gap-1 rounded-md bg-slate-100 p-1 text-sm"
      >
        {(['signin', 'signup'] as const).map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={mode === m}
            onClick={() => {
              setMode(m)
              setErrors({})
            }}
            className={`rounded px-2 py-1.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50 ${
              mode === m ? 'bg-white font-semibold shadow-sm' : 'text-slate-600 hover:text-slate-900'
            }`}
          >
            {m === 'signin' ? 'Sign in' : 'Create account'}
          </button>
        ))}
      </div>
      <form onSubmit={submit} noValidate className="space-y-3" aria-label={signup ? 'Create account' : 'Sign in'}>
        {signup && (
          <Field id="auth-name" label="Name" error={err('name')}>
            <input
              id="auth-name"
              className={inputCls}
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              aria-invalid={!!err('name')}
              aria-describedby={described('name')}
            />
          </Field>
        )}
        <Field id="auth-email" label="Email" error={err('email')}>
          <input
            id="auth-email"
            type="email"
            className={inputCls}
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!err('email')}
            aria-describedby={described('email')}
          />
        </Field>
        <Field
          id="auth-password"
          label="Password"
          error={err('password')}
          hint={signup ? 'At least 8 characters; not a common or all-number password.' : undefined}
        >
          <input
            id="auth-password"
            type="password"
            className={inputCls}
            autoComplete={signup ? 'new-password' : 'current-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!err('password')}
            aria-describedby={described('password')}
          />
        </Field>
        {signup && (
          <Field id="auth-country" label="Country" error={err('country')} hint="Sets your default units.">
            <CountrySelect id="auth-country" value={country} onChange={setCountry} error={err('country')} />
          </Field>
        )}
        {err('form') && (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-900">
            {err('form')}
          </p>
        )}
        <button type="submit" disabled={busy} className={primaryBtn}>
          {busy ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}
        </button>
        <p className="text-[11px] text-slate-500">
          An account is optional: it keeps your saved trips on every device. Routes and risk are the same either way.
        </p>
      </form>
    </Modal>
  )
}

export function AccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const user = useAuth((s) => s.user)
  const setUser = useAuth((s) => s.setUser)
  const qc = useQueryClient()
  const [name, setName] = useState(user?.name ?? '')
  const [country, setCountry] = useState(user?.country ?? '')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [deletePw, setDeletePw] = useState('')
  const [errors, setErrors] = useState<Errors>({})
  const [note, setNote] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!user) return null

  async function run(action: () => Promise<string | void>) {
    setBusy(true)
    setErrors({})
    setNote(null)
    try {
      const msg = await action()
      if (msg) setNote(msg)
    } catch (e) {
      setErrors(errorsOf(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="Account">
      <p className="mb-4 text-xs text-slate-600">
        {user.email} · {user.country_name}, {user.continent}
      </p>
      {note && (
        <p role="status" className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          {note}
        </p>
      )}
      <form
        className="space-y-3"
        aria-label="Profile"
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => {
            const res = await updateMe({ name: name.trim(), country })
            setUser(res.user)
            return 'Profile saved.'
          })
        }}
      >
        <Field id="acct-name" label="Name" error={errors.name}>
          <input id="acct-name" className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field id="acct-country" label="Country" error={errors.country}>
          <CountrySelect id="acct-country" value={country} onChange={setCountry} error={errors.country} />
        </Field>
        <button type="submit" disabled={busy} className={primaryBtn}>
          Save profile
        </button>
      </form>

      <form
        className="mt-5 space-y-3 border-t border-slate-200 pt-4"
        aria-label="Change password"
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => {
            await changePassword({ current_password: current, new_password: next })
            setCurrent('')
            setNext('')
            return 'Password changed. Other devices were signed out.'
          })
        }}
      >
        <h3 className="text-sm font-semibold">Change password</h3>
        <Field id="acct-current" label="Current password" error={errors.current_password}>
          <input
            id="acct-current"
            type="password"
            autoComplete="current-password"
            className={inputCls}
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </Field>
        <Field id="acct-new" label="New password" error={errors.new_password}>
          <input
            id="acct-new"
            type="password"
            autoComplete="new-password"
            className={inputCls}
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
        </Field>
        <button type="submit" disabled={busy || !current || !next} className={primaryBtn}>
          Change password
        </button>
      </form>

      <form
        className="mt-5 space-y-3 border-t border-slate-200 pt-4"
        aria-label="Delete account"
        onSubmit={(e) => {
          e.preventDefault()
          void run(async () => {
            await deleteMe(deletePw)
            useAuth.getState().clear()
            qc.removeQueries({ queryKey: ['trips'] })
            onClose()
          })
        }}
      >
        <h3 className="text-sm font-semibold text-red-900">Delete account</h3>
        <p className="text-xs text-slate-600">
          Permanently deletes your account and its saved trips. This cannot be undone.
        </p>
        <Field id="acct-delete" label="Confirm with your password" error={errors.password}>
          <input
            id="acct-delete"
            type="password"
            autoComplete="current-password"
            className={inputCls}
            value={deletePw}
            onChange={(e) => setDeletePw(e.target.value)}
          />
        </Field>
        <button
          type="submit"
          disabled={busy || !deletePw}
          className="w-full rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-800 hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:opacity-50"
        >
          Delete my account
        </button>
      </form>
      {errors.form && (
        <p role="alert" className="mt-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-900">
          {errors.form}
        </p>
      )}
    </Modal>
  )
}

/** Header control: "Sign in" for guests; name + menu for signed-in users. */
export function AccountMenu() {
  const user = useAuth((s) => s.user)
  const signOut = useSignOut()
  const [dialog, setDialog] = useState<null | 'signin' | 'signup' | 'account'>(null)
  const [toast, setToast] = useState<string | null>(null)
  const menu = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(t)
  }, [toast])

  const closeMenu = () => menu.current?.removeAttribute('open')
  const initials = (user?.name ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('')

  return (
    <>
      {user ? (
        <details ref={menu} className="relative" data-testid="account-menu">
          <summary
            aria-label={`Account: ${user.name}`}
            className="flex cursor-pointer list-none items-center gap-1.5 rounded-full py-0.5 pr-1 pl-0.5 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50"
          >
            <span
              aria-hidden="true"
              className="flex h-7 w-7 items-center justify-center rounded-full bg-sky-700 text-[11px] font-bold text-white"
            >
              {initials || '?'}
            </span>
            <span aria-hidden="true" className="text-[10px] text-slate-500">
              ▾
            </span>
          </summary>
          <div className="absolute right-0 z-30 mt-1 w-56 rounded-lg border border-slate-200 bg-white p-1 text-sm shadow-lg">
            <div className="px-3 py-2 text-xs">
              <p className="truncate font-semibold text-slate-900">{user.name}</p>
              <p className="truncate text-slate-500">{user.email}</p>
              <p className="text-slate-500">
                {user.country_name} · {user.continent}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                closeMenu()
                setDialog('account')
              }}
              className="block w-full rounded px-3 py-1.5 text-left hover:bg-slate-100 focus:outline-none focus-visible:bg-slate-100"
            >
              Account settings
            </button>
            <button
              type="button"
              onClick={() => {
                closeMenu()
                signOut.mutate(undefined, { onSettled: () => setToast('Signed out.') })
              }}
              className="block w-full rounded px-3 py-1.5 text-left hover:bg-slate-100 focus:outline-none focus-visible:bg-slate-100"
            >
              Sign out
            </button>
          </div>
        </details>
      ) : (
        <button
          type="button"
          onClick={() => setDialog('signin')}
          className="rounded-md border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600/50"
        >
          Sign in
        </button>
      )}

      {(dialog === 'signin' || dialog === 'signup') && (
        <AuthDialog
          open
          initialMode={dialog}
          onClose={() => setDialog(null)}
          onDone={(msg) => {
            setDialog(null)
            setToast(msg)
          }}
        />
      )}
      {dialog === 'account' && <AccountDialog open onClose={() => setDialog(null)} />}

      {toast && (
        <p
          role="status"
          className="fixed top-3 left-1/2 z-50 w-[min(420px,calc(100vw-24px))] -translate-x-1/2 rounded-lg bg-slate-900 px-4 py-2.5 text-center text-xs text-white shadow-lg"
        >
          {toast}
        </p>
      )}
    </>
  )
}
