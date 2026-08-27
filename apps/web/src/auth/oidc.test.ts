import { User } from 'oidc-client-ts'
import { describe, expect, it, vi } from 'vitest'

import {
  buildOidcManagerSettings,
  getUsableAccessToken,
  initializeOidcAuth,
  isOidcSigninCallback,
  isOidcSignoutCallback,
  readReturnUrl,
  resolveOidcConfig,
  subscribeOidcManager,
  type AuthSession,
  type OidcSessionManager,
  type OidcRuntimeConfig,
} from './oidc'

const origin = 'https://flow.example.com'
const config: OidcRuntimeConfig = {
  authority: 'https://identity.example.com',
  clientId: 'sap-ai-flow',
  redirectUri: `${origin}/auth/callback`,
  postLogoutRedirectUri: `${origin}/`,
  scope: 'openid profile email',
  audience: 'sap-ai-flow-api',
}

function oidcUser(state: unknown = undefined) {
  return new User({
    access_token: 'access-token',
    token_type: 'Bearer',
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    profile: {
      iss: 'https://identity.example.com',
      sub: 'consultant-1',
      aud: 'sap-ai-flow',
      exp: Math.floor(Date.now() / 1000) + 3600,
      iat: Math.floor(Date.now() / 1000),
      name: 'SAP 顾问',
    },
    userState: state,
  })
}

function manager(overrides: Record<string, unknown> = {}) {
  return {
    getUser: vi.fn().mockResolvedValue(null),
    removeUser: vi.fn().mockResolvedValue(undefined),
    signinSilent: vi.fn().mockResolvedValue(oidcUser()),
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinRedirectCallback: vi.fn().mockResolvedValue(oidcUser()),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    signoutRedirectCallback: vi.fn().mockResolvedValue({}),
    ...overrides,
  }
}

function tokenUser({
  accessToken,
  expiresIn,
  refreshToken,
}: {
  accessToken: string
  expiresIn: number
  refreshToken?: string
}) {
  return new User({
    access_token: accessToken,
    refresh_token: refreshToken,
    token_type: 'Bearer',
    expires_at: Math.floor(Date.now() / 1000) + expiresIn,
    profile: {
      iss: 'https://identity.example.com',
      sub: 'consultant-1',
      aud: 'sap-ai-flow',
      exp: Math.floor(Date.now() / 1000) + expiresIn,
      iat: Math.floor(Date.now() / 1000),
    },
  })
}

function sessionManager(currentUser: User | null) {
  const callbacks: {
    loaded?: (user: User) => void
    unloaded?: () => void
    expiring?: () => void | Promise<void>
    expired?: () => void | Promise<void>
  } = {}
  const removers = {
    loaded: vi.fn(),
    unloaded: vi.fn(),
    expiring: vi.fn(),
    expired: vi.fn(),
  }
  const oidcManager = {
    getUser: vi.fn().mockResolvedValue(currentUser),
    removeUser: vi.fn().mockResolvedValue(undefined),
    signinSilent: vi.fn().mockResolvedValue(null),
    events: {
      addUserLoaded: vi.fn((callback: (user: User) => void) => {
        callbacks.loaded = callback
        return removers.loaded
      }),
      addUserUnloaded: vi.fn((callback: () => void) => {
        callbacks.unloaded = callback
        return removers.unloaded
      }),
      addAccessTokenExpiring: vi.fn((callback: () => void | Promise<void>) => {
        callbacks.expiring = callback
        return removers.expiring
      }),
      addAccessTokenExpired: vi.fn((callback: () => void | Promise<void>) => {
        callbacks.expired = callback
        return removers.expired
      }),
    },
  } satisfies OidcSessionManager
  return { callbacks, oidcManager, removers }
}

describe('OIDC configuration', () => {
  it('keeps local development mode when no OIDC values are configured', () => {
    expect(resolveOidcConfig({}, 'http://localhost:5173')).toBeNull()
  })

  it('requires the authority and client id together', () => {
    expect(() =>
      resolveOidcConfig({ VITE_OIDC_AUTHORITY: 'https://identity.example.com' }, origin),
    ).toThrow('VITE_OIDC_AUTHORITY 和 VITE_OIDC_CLIENT_ID 必须同时设置')
  })

  it('builds an Authorization Code configuration backed by session storage', () => {
    const resolved = resolveOidcConfig(
      {
        VITE_OIDC_AUTHORITY: 'https://identity.example.com/',
        VITE_OIDC_CLIENT_ID: 'sap-ai-flow',
        VITE_OIDC_AUDIENCE: 'sap-ai-flow-api',
      },
      origin,
    )
    expect(resolved).toEqual(config)

    const settings = buildOidcManagerSettings(resolved!, window.sessionStorage)
    expect(settings).toMatchObject({
      response_type: 'code',
      automaticSilentRenew: false,
      redirectMethod: 'replace',
      extraQueryParams: { audience: 'sap-ai-flow-api' },
    })
    expect(settings.stateStore).toBeDefined()
    expect(settings.userStore).toBeDefined()
  })

  it('rejects callback URLs hosted outside the current SPA origin', () => {
    expect(() =>
      resolveOidcConfig(
        {
          VITE_OIDC_AUTHORITY: 'https://identity.example.com',
          VITE_OIDC_CLIENT_ID: 'sap-ai-flow',
          VITE_OIDC_REDIRECT_URI: 'https://attacker.example.com/callback',
        },
        origin,
      ),
    ).toThrow('VITE_OIDC_REDIRECT_URI 必须与当前应用同源')
  })
})

describe('OIDC callback handling', () => {
  it('recognizes sign-in and sign-out callbacks without confusing them', () => {
    expect(isOidcSigninCallback(`${origin}/auth/callback?code=abc&state=state-1`)).toBe(true)
    expect(isOidcSignoutCallback(`${origin}/?state=state-2`, `${origin}/`)).toBe(true)
    expect(isOidcSignoutCallback(`${origin}/auth/callback?code=abc&state=x`, `${origin}/`)).toBe(false)
  })

  it('finishes the sign-in callback and restores the same-origin return URL', async () => {
    const user = oidcUser({ returnUrl: '/workspace?project=project-1' })
    const oidcManager = manager({ signinRedirectCallback: vi.fn().mockResolvedValue(user) })
    const replace = vi.fn()

    await expect(
      initializeOidcAuth({
        config,
        manager: oidcManager,
        browser: {
          href: `${origin}/auth/callback?code=abc&state=state-1`,
          origin,
          replace,
        },
      }),
    ).resolves.toEqual({
      configured: true,
      authenticated: true,
      userId: 'consultant-1',
      displayName: 'SAP 顾问',
    })
    expect(oidcManager.signinRedirectCallback).toHaveBeenCalledWith(
      `${origin}/auth/callback?code=abc&state=state-1`,
    )
    expect(replace).toHaveBeenCalledWith('/workspace?project=project-1')
  })

  it('cleans the logout callback and does not accept an external return URL', async () => {
    expect(readReturnUrl('https://attacker.example.com/steal', origin)).toBe('/')
    const oidcManager = manager()
    const replace = vi.fn()

    await expect(
      initializeOidcAuth({
        config,
        manager: oidcManager,
        browser: { href: `${origin}/?state=logout-state`, origin, replace },
      }),
    ).resolves.toMatchObject({ configured: true, authenticated: false })
    expect(oidcManager.signoutRedirectCallback).toHaveBeenCalledWith(
      `${origin}/?state=logout-state`,
    )
    expect(oidcManager.removeUser).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith('/')
  })
})

describe('OIDC token lifecycle', () => {
  it('renews an expiring access token with a refresh token', async () => {
    const currentUser = tokenUser({
      accessToken: 'expiring-access-token',
      expiresIn: 30,
      refreshToken: 'refresh-token',
    })
    const renewedUser = tokenUser({ accessToken: 'renewed-access-token', expiresIn: 3600 })
    const oidcManager = manager({
      getUser: vi.fn().mockResolvedValue(currentUser),
      signinSilent: vi.fn().mockResolvedValue(renewedUser),
    })

    await expect(getUsableAccessToken(oidcManager)).resolves.toBe('renewed-access-token')
    expect(oidcManager.signinSilent).toHaveBeenCalledTimes(1)
    expect(oidcManager.removeUser).not.toHaveBeenCalled()
  })

  it('coalesces concurrent refresh-token renewals', async () => {
    const currentUser = tokenUser({
      accessToken: 'expiring-access-token',
      expiresIn: 30,
      refreshToken: 'refresh-token',
    })
    const renewedUser = tokenUser({ accessToken: 'renewed-access-token', expiresIn: 3600 })
    let resolveRenewal: ((user: User) => void) | undefined
    const renewal = new Promise<User>((resolve) => {
      resolveRenewal = resolve
    })
    const oidcManager = manager({
      getUser: vi.fn().mockResolvedValue(currentUser),
      signinSilent: vi.fn().mockReturnValue(renewal),
    })

    const first = getUsableAccessToken(oidcManager)
    const second = getUsableAccessToken(oidcManager)
    await vi.waitFor(() => expect(oidcManager.signinSilent).toHaveBeenCalledTimes(1))
    resolveRenewal!(renewedUser)
    await expect(Promise.all([first, second])).resolves.toEqual([
      'renewed-access-token',
      'renewed-access-token',
    ])
  })

  it('removes an expired session when no refresh token is available', async () => {
    const currentUser = tokenUser({ accessToken: 'expired-access-token', expiresIn: -60 })
    const oidcManager = manager({ getUser: vi.fn().mockResolvedValue(currentUser) })

    await expect(getUsableAccessToken(oidcManager)).resolves.toBeUndefined()
    expect(oidcManager.signinSilent).not.toHaveBeenCalled()
    expect(oidcManager.removeUser).toHaveBeenCalledTimes(1)
  })

  it('updates the application session when an access token expires', async () => {
    const currentUser = tokenUser({ accessToken: 'expired-access-token', expiresIn: -60 })
    const { callbacks, oidcManager, removers } = sessionManager(currentUser)
    const sessions: AuthSession[] = []
    const errors: string[] = []
    const unsubscribe = subscribeOidcManager(
      oidcManager,
      (session) => sessions.push(session),
      (message) => errors.push(message),
    )

    await callbacks.expired!()

    expect(oidcManager.removeUser).toHaveBeenCalledTimes(1)
    expect(sessions.at(-1)).toEqual({
      configured: true,
      authenticated: false,
      userId: null,
      displayName: null,
    })
    expect(errors).toEqual(['登录已过期，请重新登录。'])

    unsubscribe()
    expect(Object.values(removers).every((remove) => remove.mock.calls.length === 1)).toBe(true)
  })

  it('renews the application session from the access-token expiring event', async () => {
    const currentUser = tokenUser({
      accessToken: 'expiring-access-token',
      expiresIn: 30,
      refreshToken: 'refresh-token',
    })
    const renewedUser = tokenUser({ accessToken: 'renewed-access-token', expiresIn: 3600 })
    const { callbacks, oidcManager } = sessionManager(currentUser)
    oidcManager.signinSilent.mockResolvedValue(renewedUser)
    const sessions: AuthSession[] = []
    const errors: string[] = []
    const unsubscribe = subscribeOidcManager(
      oidcManager,
      (session) => sessions.push(session),
      (message) => errors.push(message),
    )

    await callbacks.expiring!()

    expect(oidcManager.signinSilent).toHaveBeenCalledTimes(1)
    expect(sessions.at(-1)).toMatchObject({
      configured: true,
      authenticated: true,
      userId: 'consultant-1',
    })
    expect(errors).toEqual([])
    unsubscribe()
  })
})
