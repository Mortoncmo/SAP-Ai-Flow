import { User } from 'oidc-client-ts'
import { describe, expect, it, vi } from 'vitest'

import {
  buildOidcManagerSettings,
  initializeOidcAuth,
  isOidcSigninCallback,
  isOidcSignoutCallback,
  readReturnUrl,
  resolveOidcConfig,
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
    signinRedirect: vi.fn().mockResolvedValue(undefined),
    signinRedirectCallback: vi.fn().mockResolvedValue(oidcUser()),
    signoutRedirect: vi.fn().mockResolvedValue(undefined),
    signoutRedirectCallback: vi.fn().mockResolvedValue({}),
    ...overrides,
  }
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
    expect(replace).toHaveBeenCalledWith('/')
  })
})
