import {
  UserManager,
  WebStorageStateStore,
  type User,
  type UserManagerSettings,
} from 'oidc-client-ts'

export interface OidcEnvironment {
  VITE_OIDC_AUTHORITY?: string
  VITE_OIDC_CLIENT_ID?: string
  VITE_OIDC_REDIRECT_URI?: string
  VITE_OIDC_POST_LOGOUT_REDIRECT_URI?: string
  VITE_OIDC_SCOPE?: string
  VITE_OIDC_AUDIENCE?: string
}

export interface OidcRuntimeConfig {
  authority: string
  clientId: string
  redirectUri: string
  postLogoutRedirectUri: string
  scope: string
  audience?: string
}

export interface AuthSession {
  configured: boolean
  authenticated: boolean
  userId: string | null
  displayName: string | null
}

type OidcManager = Pick<
  UserManager,
  | 'getUser'
  | 'removeUser'
  | 'signinSilent'
  | 'signinRedirect'
  | 'signinRedirectCallback'
  | 'signoutRedirect'
  | 'signoutRedirectCallback'
>

interface OidcSessionEvents {
  addUserLoaded: (callback: (user: User) => void) => () => void
  addUserUnloaded: (callback: () => void) => () => void
  addAccessTokenExpiring: (callback: () => void) => () => void
  addAccessTokenExpired: (callback: () => void) => () => void
}

export interface OidcSessionManager
  extends Pick<OidcManager, 'getUser' | 'removeUser' | 'signinSilent'> {
  events: OidcSessionEvents
}

interface OidcBrowser {
  href: string
  origin: string
  replace: (url: string) => void
}

interface InitializeOidcOptions {
  config?: OidcRuntimeConfig | null
  manager?: OidcManager
  browser?: OidcBrowser
}

let runtimeConfig: OidcRuntimeConfig | null | undefined
let userManager: UserManager | undefined
let runtimeInitialization: Promise<AuthSession> | undefined
const renewalPromises = new WeakMap<object, Promise<User | null>>()
const signingOutManagers = new WeakSet<object>()
const tokenRenewalWindowSeconds = 60

export function resolveOidcConfig(
  env: OidcEnvironment,
  browserOrigin: string,
): OidcRuntimeConfig | null {
  const authority = env.VITE_OIDC_AUTHORITY?.trim() ?? ''
  const clientId = env.VITE_OIDC_CLIENT_ID?.trim() ?? ''
  const redirectUri = env.VITE_OIDC_REDIRECT_URI?.trim() ?? ''
  const postLogoutRedirectUri = env.VITE_OIDC_POST_LOGOUT_REDIRECT_URI?.trim() ?? ''
  const audience = env.VITE_OIDC_AUDIENCE?.trim() || undefined
  const hasAnyConfiguration = Boolean(
    authority || clientId || redirectUri || postLogoutRedirectUri || audience,
  )

  if (!hasAnyConfiguration) return null
  if (!authority || !clientId) {
    throw new Error('OIDC 配置不完整：VITE_OIDC_AUTHORITY 和 VITE_OIDC_CLIENT_ID 必须同时设置。')
  }

  const origin = new URL(browserOrigin).origin
  const normalizedAuthority = parseHttpUrl(authority, 'VITE_OIDC_AUTHORITY').toString().replace(/\/$/, '')
  const normalizedRedirectUri = parseSameOriginUrl(
    redirectUri || `${origin}/auth/callback`,
    origin,
    'VITE_OIDC_REDIRECT_URI',
  )
  const normalizedPostLogoutRedirectUri = parseSameOriginUrl(
    postLogoutRedirectUri || `${origin}/`,
    origin,
    'VITE_OIDC_POST_LOGOUT_REDIRECT_URI',
  )
  const scope = env.VITE_OIDC_SCOPE?.trim() || 'openid profile email'
  if (!scope.split(/\s+/).includes('openid')) {
    throw new Error('OIDC 配置错误：VITE_OIDC_SCOPE 必须包含 openid。')
  }

  return {
    authority: normalizedAuthority,
    clientId,
    redirectUri: normalizedRedirectUri,
    postLogoutRedirectUri: normalizedPostLogoutRedirectUri,
    scope,
    audience,
  }
}

export function buildOidcManagerSettings(
  config: OidcRuntimeConfig,
  storage: Storage,
): UserManagerSettings {
  return {
    authority: config.authority,
    client_id: config.clientId,
    redirect_uri: config.redirectUri,
    post_logout_redirect_uri: config.postLogoutRedirectUri,
    response_type: 'code',
    scope: config.scope,
    loadUserInfo: false,
    automaticSilentRenew: false,
    monitorSession: false,
    redirectMethod: 'replace',
    stateStore: new WebStorageStateStore({ prefix: 'sap-ai-flow.oidc.state.', store: storage }),
    userStore: new WebStorageStateStore({ prefix: 'sap-ai-flow.oidc.user.', store: storage }),
    extraQueryParams: config.audience ? { audience: config.audience } : undefined,
  }
}

export async function initializeOidcAuth(
  options: InitializeOidcOptions = {},
): Promise<AuthSession> {
  const usesRuntimeDependencies =
    options.config === undefined && options.manager === undefined && options.browser === undefined
  if (usesRuntimeDependencies) {
    runtimeInitialization ??= initializeOidcAuthInternal(options).catch((error: unknown) => {
      runtimeInitialization = undefined
      throw error
    })
    return runtimeInitialization
  }
  return initializeOidcAuthInternal(options)
}

async function initializeOidcAuthInternal(
  options: InitializeOidcOptions,
): Promise<AuthSession> {
  const config = options.config === undefined ? getRuntimeConfig() : options.config
  if (!config) return anonymousSession(false)

  const manager = options.manager ?? getUserManager(config)
  const browser = options.browser ?? getBrowser()
  let user: User | null

  if (isOidcSignoutCallback(browser.href, config.postLogoutRedirectUri)) {
    try {
      await manager.signoutRedirectCallback(browser.href)
      user = null
    } finally {
      await manager.removeUser().catch(() => undefined)
      browser.replace(relativeUrl(config.postLogoutRedirectUri))
    }
  } else if (isOidcSigninCallback(browser.href)) {
    try {
      user = await manager.signinRedirectCallback(browser.href)
      browser.replace(readReturnUrl(user.state, browser.origin))
    } catch (error) {
      browser.replace('/')
      throw error
    }
  } else {
    user = await manager.getUser()
  }

  if (user?.expired) {
    await manager.removeUser()
    user = null
  }
  return sessionFromUser(user)
}

export async function startOidcSignIn(): Promise<void> {
  const config = requireRuntimeConfig()
  const browser = getBrowser()
  const manager = getUserManager(config)
  signingOutManagers.delete(manager)
  await manager.signinRedirect({
    state: { returnUrl: readReturnUrl(browser.href, browser.origin) },
  })
}

export async function startOidcSignOut(): Promise<void> {
  const config = requireRuntimeConfig()
  const manager = getUserManager(config)
  signingOutManagers.add(manager)
  try {
    await manager.signoutRedirect()
  } catch (error) {
    signingOutManagers.delete(manager)
    throw error
  }
}

export async function getAccessToken(): Promise<string | undefined> {
  const config = getRuntimeConfig()
  if (!config) return undefined
  return getUsableAccessToken(getUserManager(config))
}

export async function clearOidcSession(): Promise<void> {
  const config = getRuntimeConfig()
  if (!config) return
  await getUserManager(config).removeUser()
}

export async function getUsableAccessToken(
  manager: Pick<OidcManager, 'getUser' | 'removeUser' | 'signinSilent'>,
): Promise<string | undefined> {
  const user = await manager.getUser()
  if (!user?.access_token) return undefined

  const shouldRenew = Boolean(
    user.refresh_token
    && (user.expired || (user.expires_in !== undefined && user.expires_in <= tokenRenewalWindowSeconds)),
  )
  if (shouldRenew) {
    try {
      const renewedUser = await renewWithRefreshToken(manager)
      if (renewedUser?.access_token && !renewedUser.expired) return renewedUser.access_token
    } catch {
      if (!user.expired) return user.access_token
    }
  }

  if (user.expired) {
    await manager.removeUser().catch(() => undefined)
    return undefined
  }
  return user.access_token
}

export function subscribeOidcAuth(
  onSession: (session: AuthSession) => void,
  onError: (message: string) => void,
): () => void {
  const config = getRuntimeConfig()
  if (!config) return () => undefined
  return subscribeOidcManager(getUserManager(config), onSession, onError)
}

export function subscribeOidcManager(
  manager: OidcSessionManager,
  onSession: (session: AuthSession) => void,
  onError: (message: string) => void,
): () => void {
  let active = true
  const updateSession = (user: User | null) => {
    if (active) onSession(sessionFromUser(user))
  }
  const renewIfPossible = async () => {
    const user = await manager.getUser()
    if (!user?.refresh_token) return null
    return renewWithRefreshToken(manager)
  }
  const handleExpiring = async () => {
    try {
      const renewedUser = await renewIfPossible()
      if (renewedUser) updateSession(renewedUser)
    } catch {
      // Keep a still-valid access token. The expired event performs the final retry.
    }
  }
  const handleExpired = async () => {
    try {
      const renewedUser = await renewIfPossible()
      if (renewedUser?.access_token && !renewedUser.expired) {
        updateSession(renewedUser)
        return
      }
    } catch {
      // The session is cleared below so an expired token is never reused.
    }
    await manager.removeUser().catch(() => undefined)
    updateSession(null)
    if (active) onError('登录已过期，请重新登录。')
  }

  const removeUserLoaded = manager.events.addUserLoaded(updateSession)
  const removeUserUnloaded = manager.events.addUserUnloaded(() => updateSession(null))
  const removeAccessTokenExpiring = manager.events.addAccessTokenExpiring(handleExpiring)
  const removeAccessTokenExpired = manager.events.addAccessTokenExpired(handleExpired)

  return () => {
    active = false
    removeUserLoaded()
    removeUserUnloaded()
    removeAccessTokenExpiring()
    removeAccessTokenExpired()
  }
}

function renewWithRefreshToken(
  manager: Pick<OidcManager, 'removeUser' | 'signinSilent'>,
): Promise<User | null> {
  const existing = renewalPromises.get(manager)
  if (existing) return existing

  const renewal = manager
    .signinSilent()
    .then(async (user) => {
      if (!signingOutManagers.has(manager)) return user
      await manager.removeUser().catch(() => undefined)
      return null
    })
    .finally(() => renewalPromises.delete(manager))
  renewalPromises.set(manager, renewal)
  return renewal
}

export function isOidcSigninCallback(url: string): boolean {
  const search = new URL(url).searchParams
  return Boolean(search.get('state') && (search.get('code') || search.get('error')))
}

export function isOidcSignoutCallback(url: string, postLogoutRedirectUri: string): boolean {
  const current = new URL(url)
  const expected = new URL(postLogoutRedirectUri)
  return (
    current.origin === expected.origin &&
    current.pathname === expected.pathname &&
    Boolean(current.searchParams.get('state')) &&
    !current.searchParams.get('code') &&
    !current.searchParams.get('error')
  )
}

export function readReturnUrl(value: unknown, origin: string): string {
  const candidate =
    typeof value === 'string'
      ? value
      : isRecord(value) && typeof value.returnUrl === 'string'
        ? value.returnUrl
        : '/'
  try {
    const url = new URL(candidate, origin)
    if (url.origin !== new URL(origin).origin) return '/'
    return relativeUrl(url.toString())
  } catch {
    return '/'
  }
}

function getRuntimeConfig(): OidcRuntimeConfig | null {
  if (runtimeConfig === undefined) {
    runtimeConfig = resolveOidcConfig(import.meta.env, window.location.origin)
  }
  return runtimeConfig
}

function requireRuntimeConfig(): OidcRuntimeConfig {
  const config = getRuntimeConfig()
  if (!config) throw new Error('当前环境未配置 OIDC。')
  return config
}

function getUserManager(config: OidcRuntimeConfig): UserManager {
  userManager ??= new UserManager(buildOidcManagerSettings(config, window.sessionStorage))
  return userManager
}

function getBrowser(): OidcBrowser {
  return {
    href: window.location.href,
    origin: window.location.origin,
    replace: (url) => window.history.replaceState(window.history.state, document.title, url),
  }
}

function sessionFromUser(user: User | null): AuthSession {
  if (!user) return anonymousSession(true)
  const userId = readClaim(user.profile.sub)
  const displayName =
    readClaim(user.profile.name) ??
    readClaim(user.profile.preferred_username) ??
    readClaim(user.profile.email) ??
    userId
  return {
    configured: true,
    authenticated: Boolean(user.access_token && !user.expired),
    userId,
    displayName,
  }
}

function anonymousSession(configured: boolean): AuthSession {
  return { configured, authenticated: false, userId: null, displayName: null }
}

function parseHttpUrl(value: string, name: string): URL {
  let parsed: URL
  try {
    parsed = new URL(value)
  } catch {
    throw new Error(`OIDC 配置错误：${name} 不是有效 URL。`)
  }
  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new Error(`OIDC 配置错误：${name} 必须使用 http 或 https。`)
  }
  return parsed
}

function parseSameOriginUrl(value: string, origin: string, name: string): string {
  const parsed = parseHttpUrl(value, name)
  if (parsed.origin !== origin) {
    throw new Error(`OIDC 配置错误：${name} 必须与当前应用同源。`)
  }
  return parsed.toString()
}

function relativeUrl(value: string): string {
  const parsed = new URL(value)
  return `${parsed.pathname}${parsed.search}${parsed.hash}`
}

function readClaim(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
