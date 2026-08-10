async page => {
  const appOrigin = 'http://127.0.0.1:8080'
  const oidcOrigin = 'http://127.0.0.1:9080'
  const userId = 'ci-consultant'
  const projectName = 'OIDC CI Acceptance Project'
  const consoleErrors = []
  const pageErrors = []
  let tokenRequestBody = ''
  let stage = 'opening application'
  const assert = (condition, message) => {
    if (!condition) throw new Error(message)
  }

  page.on('console', message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', error => pageErrors.push(error.message))
  page.on('request', request => {
    if (request.url() === `${oidcOrigin}/ci/token`) {
      tokenRequestBody = request.postData() ?? ''
    }
  })

  try {
    await page.goto(appOrigin, { waitUntil: 'domcontentloaded' })
    const signIn = page.getByRole('button', { name: '\u767b\u5f55' })
    await signIn.waitFor()

    stage = 'starting authorization code flow'
    await signIn.click()
    await page.waitForURL(url => url.href.startsWith(`${oidcOrigin}/ci/authorize`))
    const authorization = new URL(page.url())
    assert(authorization.searchParams.get('response_type') === 'code', 'OIDC did not use code flow')
    assert(authorization.searchParams.get('client_id') === 'sap-ai-flow-ci-web', 'OIDC client id mismatch')
    assert(authorization.searchParams.get('code_challenge_method') === 'S256', 'PKCE method is not S256')
    assert(Boolean(authorization.searchParams.get('code_challenge')), 'PKCE code challenge is missing')
    assert(
      authorization.searchParams.get('redirect_uri') === `${appOrigin}/auth/callback`,
      'OIDC redirect URI mismatch',
    )

    stage = 'submitting test identity'
    await page.locator('input[name="username"]').fill(userId)
    await page.locator('input[type="submit"]').click()
    await page.waitForURL(url => url.href.startsWith(`${appOrigin}/auth/callback`))
    const identity = page.locator('.auth-control__identity')
    await identity.waitFor()
    assert(await identity.textContent() === 'CI SAP Consultant', 'OIDC display name was not rendered')
    assert(await identity.getAttribute('title') === userId, 'OIDC subject was not retained')
    assert(tokenRequestBody.includes('grant_type=authorization_code'), 'authorization code was not exchanged')
    assert(tokenRequestBody.includes('code_verifier='), 'PKCE code verifier was not sent')

    stage = 'calling protected tenant-scoped API'
    const createResponsePromise = page.waitForResponse(response => (
      response.url() === `${appOrigin}/api/v1/projects`
      && response.request().method() === 'POST'
    ))
    const promptPromise = page.waitForEvent('dialog')
    await page.getByRole('button', { name: '\u65b0\u5efa\u9879\u76ee' }).click()
    const prompt = await promptPromise
    assert(prompt.type() === 'prompt', 'new project did not use the expected prompt')
    await prompt.accept(projectName)
    const createResponse = await createResponsePromise
    assert(createResponse.status() === 201, `protected project API returned ${createResponse.status()}`)
    const authorizationHeader = (await createResponse.request().allHeaders()).authorization ?? ''
    assert(authorizationHeader.startsWith('Bearer '), 'protected API request omitted Bearer token')
    const project = await createResponse.json()
    assert(project.current_role === 'project_admin', 'OIDC project role was not assigned')
    await page.waitForFunction(name => (
      [...document.querySelectorAll('select[aria-label="\u9879\u76ee"] option')]
        .some(option => option.textContent?.includes(name))
    ), projectName)

    stage = 'logging out'
    await page.getByRole('button', { name: '\u9000\u51fa\u767b\u5f55' }).click()
    await page.waitForURL(url => url.href.startsWith(`${appOrigin}/`))
    await page.getByRole('button', { name: '\u767b\u5f55' }).waitFor()
    assert(
      await page.locator('select[aria-label="\u9879\u76ee"]').isDisabled(),
      'project selector remained enabled after logout',
    )
    assert((await page.request.get(`${appOrigin}/api/v1/projects`)).status() === 401, 'anonymous API was not rejected')
    assert(consoleErrors.length === 0, `browser console errors: ${consoleErrors.join(' | ')}`)
    assert(pageErrors.length === 0, `uncaught page errors: ${pageErrors.join(' | ')}`)
  } catch (error) {
    throw new Error(`[${stage}] ${error.message}`)
  }
}
