async page => {
  const consoleErrors = []
  const captureConsoleError = message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  }
  page.on('console', captureConsoleError)

  try {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('.canvas-region').waitFor()

    const initialNodes = await page.locator('.react-flow__node-business').count()
    const initialLanes = await page.locator('.lane-editor__name').count()
    if (initialNodes !== 7 || initialLanes !== 5) {
      throw new Error(`expected 7 business nodes and 5 lanes, got ${initialNodes}/${initialLanes}`)
    }

    await page.locator('.lane-manager__heading button').click()
    const buttonNodes = await page.locator('.react-flow__node-business').count()
    const buttonLanes = await page.locator('.lane-editor__name').count()
    if (buttonNodes !== 7 || buttonLanes !== 6) {
      throw new Error(`adding a lane changed the wrong collection: ${buttonNodes}/${buttonLanes}`)
    }

    await page.locator('.command-dock textarea').fill(
      '\u589e\u52a0\u6cf3\u9053\uff1a\u9500\u552e\u3001\u7269\u6d41\u3001\u8d22\u52a1',
    )
    await page.locator('.command-dock button[type=submit]').click()
    await page.waitForFunction(() =>
      [...document.querySelectorAll('.lane-editor__name')].some(
        element => element.value === '\u9500\u552e',
      ),
    )

    const finalNodes = await page.locator('.react-flow__node-business').count()
    const labels = await page.locator('.lane-editor__name').evaluateAll(elements =>
      elements.map(element => element.value),
    )
    if (finalNodes !== 7 || labels.filter(label => label === '\u8d22\u52a1').length !== 1) {
      throw new Error(
        `natural-language lane edit changed nodes or duplicated finance: ${finalNodes}/${labels.join(',')}`,
      )
    }
    for (const required of ['\u9500\u552e', '\u7269\u6d41']) {
      if (!labels.includes(required)) throw new Error(`missing lane: ${required}`)
    }

    await page.setViewportSize({ width: 390, height: 844 })
    const widths = await page.evaluate(() => ({
      viewport: window.innerWidth,
      body: document.body.scrollWidth,
      root: document.documentElement.scrollWidth,
    }))
    if (widths.viewport !== 390 || widths.body !== 390 || widths.root !== 390) {
      throw new Error(`mobile overflow detected: ${JSON.stringify(widths)}`)
    }
    if (consoleErrors.length > 0) {
      throw new Error(`browser console errors: ${consoleErrors.join(' | ')}`)
    }
  } finally {
    page.off('console', captureConsoleError)
  }
}
