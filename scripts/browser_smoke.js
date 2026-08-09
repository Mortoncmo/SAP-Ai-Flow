async page => {
  const adminUserId = 'local-user'
  const viewerUserId = 'browser-smoke-viewer'
  const projectName = '浏览器自动验收项目'
  const processName = 'P2P 浏览器验收流程'
  const managedEnvironment = page.url().includes('browserSmokeManaged=1')
  let stage = 'initializing'
  const consoleErrors = []
  const pageErrors = []
  const captureConsoleError = message => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  }
  const capturePageError = error => pageErrors.push(error.message)
  const assert = (condition, message) => {
    if (!condition) throw new Error(message)
  }

  const waitForSelectOption = async (label, value) => {
    await page.waitForFunction(
      ({ label, value }) => [...document.querySelectorAll(`select[aria-label="${label}"] option`)]
        .some(option => option.value === value),
      { label, value },
    )
  }

  const openFixture = async fixture => {
    stage = 'opening project fixture'
    await page.reload({ waitUntil: 'domcontentloaded' })
    const projectSelect = page.locator('select[aria-label="\u9879\u76ee"]')
    await projectSelect.waitFor()
    await waitForSelectOption('\u9879\u76ee', fixture.projectId)
    await projectSelect.selectOption(fixture.projectId)
    await waitForSelectOption('\u6d41\u7a0b', fixture.processId)
    await page.locator('select[aria-label="\u6d41\u7a0b"]').selectOption(fixture.processId)
    await page.locator('.canvas-region').waitFor()
    await page.locator('.command-dock__status').filter({ hasText: processName }).waitFor()
  }

  const viewportWidths = () => page.evaluate(() => ({
    viewport: window.innerWidth,
    body: document.body.scrollWidth,
    root: document.documentElement.scrollWidth,
  }))

  const assertViewport = async (width, height) => {
    await page.setViewportSize({ width, height })
    const widths = await viewportWidths()
    assert(
      widths.viewport === width && widths.body === width && widths.root === width,
      `viewport overflow detected at ${width}x${height}: ${JSON.stringify(widths)}`,
    )
  }

  const readDownload = async download => {
    const stream = await download.createReadStream()
    assert(stream, `download stream unavailable: ${download.suggestedFilename()}`)
    let bytes = 0
    const prefix = []
    const decoder = new TextDecoder('utf-8')
    let text = ''
    for await (const chunk of stream) {
      bytes += chunk.length
      for (let index = 0; index < chunk.length && prefix.length < 4; index += 1) {
        prefix.push(chunk[index])
      }
      if (download.suggestedFilename().endsWith('.md')) {
        text += decoder.decode(chunk, { stream: true })
      }
    }
    if (download.suggestedFilename().endsWith('.md')) text += decoder.decode()
    return { bytes, prefix, text }
  }

  const downloadBlueprint = async (label, extension) => {
    const exportJobResponsePromise = page.waitForResponse(response => (
      response.url().endsWith('/exports/jobs')
      && response.request().method() === 'POST'
    ))
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: label }).click()
    const exportJobResponse = await exportJobResponsePromise
    assert(exportJobResponse.status() === 202, `${label} export job returned ${exportJobResponse.status()}`)
    const exportJob = await exportJobResponse.json()
    assert(typeof exportJob.export_id === 'string' && exportJob.export_id.length > 0, `${label} export job has no export_id`)
    assert(exportJob.status === 'pending', `${label} export job started as ${exportJob.status}`)
    const download = await downloadPromise
    const failure = await download.failure()
    assert(failure === null, `${label} failed: ${failure}`)
    const filename = download.suggestedFilename()
    assert(filename.includes(processName), `${label} filename lost the process name: ${filename}`)
    assert(filename.endsWith(extension), `${label} filename has the wrong extension: ${filename}`)
    const content = await readDownload(download)
    assert(content.bytes > 100, `${label} returned an unexpectedly small file: ${content.bytes}`)
    return { filename, exportId: exportJob.export_id, ...content }
  }

  const submitLocalInstruction = async instruction => {
    await page.locator('.command-dock textarea').fill(instruction)
    const responsePromise = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/flowcharts/modify')
      && response.request().method() === 'POST',
    )
    await page.locator('.command-dock button[type=submit]').click()
    const response = await responsePromise
    assert(response.ok(), `local instruction returned ${response.status()}: ${instruction}`)
    const payload = await response.json()
    await page.locator('.command-dock__status').filter({ hasText: payload.applied_patch.change_summary }).waitFor()
    return payload.graph
  }

  page.on('console', captureConsoleError)
  page.on('pageerror', capturePageError)
  await page.context().setExtraHTTPHeaders({ 'X-User-ID': adminUserId })

  let fixture = null
  try {
    // Local demo regression: adding swimlanes must never add process nodes.
    stage = 'loading local demo'
    await page.evaluate(() => localStorage.removeItem('sap-ai-flow-state'))
    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('.canvas-region').waitFor()

    const initialNodes = await page.locator('.react-flow__node-business').count()
    const initialLanes = await page.locator('.lane-editor__name').count()
    assert(
      initialNodes === 7 && initialLanes === 5,
      `expected 7 business nodes and 5 lanes, got ${initialNodes}/${initialLanes}`,
    )

    stage = 'testing local history and recovery'
    const storedVersion = () => page.evaluate(() => {
      const persisted = JSON.parse(localStorage.getItem('sap-ai-flow-state') || '{}')
      return persisted.state?.graph?.version
    })
    const initialVersion = (await storedVersion()) ?? 0
    const verticalButton = page.locator('.segmented button').filter({ hasText: '\u7eb5\u5411' })
    const horizontalButton = page.locator('.segmented button').filter({ hasText: '\u6a2a\u5411' })
    assert(await horizontalButton.getAttribute('class') === 'is-active', 'sample graph is not horizontal')
    await verticalButton.click()
    await page.getByRole('button', { name: '\u81ea\u52a8\u5e03\u5c40' }).click()
    await page.waitForFunction(expected => {
      const persisted = JSON.parse(localStorage.getItem('sap-ai-flow-state') || '{}')
      return persisted.state?.graph?.version === expected
    }, initialVersion + 2)

    await page.getByRole('button', { name: '\u64a4\u9500' }).click()
    assert(await storedVersion() === initialVersion + 1, 'first undo did not restore the direction change')
    await page.getByRole('button', { name: '\u64a4\u9500' }).click()
    assert(await storedVersion() === initialVersion, 'second undo did not restore the initial graph')
    assert(await horizontalButton.getAttribute('class') === 'is-active', 'undo did not restore horizontal layout')

    await page.getByRole('button', { name: '\u91cd\u505a' }).click()
    assert(await storedVersion() === initialVersion + 1, 'first redo did not restore the direction change')
    await page.getByRole('button', { name: '\u91cd\u505a' }).click()
    assert(await storedVersion() === initialVersion + 2, 'second redo did not restore auto layout')
    assert(await verticalButton.getAttribute('class') === 'is-active', 'redo did not restore vertical layout')

    await page.reload({ waitUntil: 'domcontentloaded' })
    await page.locator('.canvas-region').waitFor()
    assert(await verticalButton.getAttribute('class') === 'is-active', 'reload did not recover the local graph')
    assert(await storedVersion() === initialVersion + 2, 'reload lost the recovered graph version')
    assert(await page.locator('.react-flow__node-business').count() === 7, 'reload lost process nodes')
    assert(await page.locator('.lane-editor__name').count() === 5, 'reload lost swimlanes')
    await horizontalButton.click()
    assert(await horizontalButton.getAttribute('class') === 'is-active', 'failed to restore horizontal layout')

    await page.locator('.lane-manager__heading button').click()
    const buttonNodes = await page.locator('.react-flow__node-business').count()
    const buttonLanes = await page.locator('.lane-editor__name').count()
    assert(
      buttonNodes === 7 && buttonLanes === 6,
      `adding a lane changed the wrong collection: ${buttonNodes}/${buttonLanes}`,
    )

    await page.locator('.command-dock textarea').fill(
      '\u589e\u52a0\u6cf3\u9053\uff1a\u9500\u552e\u3001\u7269\u6d41\u3001\u8d22\u52a1',
    )
    stage = 'submitting natural-language swimlanes'
    const laneResponsePromise = page.waitForResponse(response =>
      response.url().endsWith('/api/v1/flowcharts/modify')
      && response.request().method() === 'POST',
    )
    await page.locator('.command-dock button[type=submit]').click()
    const laneResponse = await laneResponsePromise
    assert(laneResponse.ok(), `swimlane modify request returned ${laneResponse.status()}`)
    const lanePayload = await laneResponse.json()
    assert(
      lanePayload.graph.lanes.some(lane => lane.label === '\u9500\u552e'),
      `swimlane modify response is missing sales: ${lanePayload.graph.lanes.map(lane => lane.label).join(',')}`,
    )
    const apiRoot = laneResponse.url().match(/^https?:\/\/[^/]+/)?.[0]
    assert(apiRoot, `could not determine API origin from ${laneResponse.url()}`)

    stage = 'checking local patch P95 performance'
    const localPatchDurations = []
    for (let index = 0; index < 20; index += 1) {
      const startedAt = Date.now()
      const response = await page.request.post(`${apiRoot}/api/v1/flowcharts/modify`, {
        headers: { 'X-User-ID': adminUserId },
        data: {
          request_id: `browser_performance_${index}`,
          current_graph: lanePayload.graph,
          instruction: '\u7ed9\u53d1\u7968\u6821\u9a8c\u589e\u52a0\u6587\u4ef6\u56fe\u6807',
          locale: 'zh-CN',
        },
      })
      assert(response.ok(), `local patch performance request returned ${response.status()}`)
      localPatchDurations.push(Date.now() - startedAt)
    }
    const sortedDurations = [...localPatchDurations].sort((left, right) => left - right)
    const localPatchP95Ms = sortedDurations[Math.ceil(sortedDurations.length * 0.95) - 1]
    assert(
      localPatchP95Ms < 1_000,
      `local patch P95 exceeded 1000 ms: ${localPatchP95Ms} (${localPatchDurations.join(',')})`,
    )
    stage = 'applying natural-language swimlanes in the UI'
    await page.locator('.command-dock__status').filter({ hasText: '\u589e\u52a0\u6cf3\u9053' }).waitFor()

    const finalNodes = await page.locator('.react-flow__node-business').count()
    const labels = await page.locator('.lane-editor__name').evaluateAll(elements =>
      elements.map(element => element.value),
    )
    assert(
      finalNodes === 7 && labels.filter(label => label === '\u8d22\u52a1').length === 1,
      `natural-language lane edit changed nodes or duplicated finance: ${finalNodes}/${labels.join(',')}`,
    )
    for (const required of ['\u9500\u552e', '\u7269\u6d41']) {
      assert(labels.includes(required), `missing lane: ${required}`)
    }

    stage = 'testing natural-language edge operations'
    const edgeNodeCount = await page.locator('.react-flow__node-business').count()
    const edgeLaneCount = await page.locator('.lane-editor__name').count()
    const edgeCountBefore = await page.locator('.react-flow__edge').count()
    let edgeGraph = await submitLocalInstruction('\u8fde\u63a5\u5f00\u59cb\u5230\u7ed3\u675f')
    const directEdge = edgeGraph.edges.find(edge => edge.source === 'start' && edge.target === 'end')
    assert(directEdge, 'natural-language edge creation did not add start -> end')
    assert(edgeGraph.nodes.length === edgeNodeCount, 'edge creation changed process nodes')
    assert(edgeGraph.lanes.length === edgeLaneCount, 'edge creation changed swimlanes')
    assert(await page.locator('.react-flow__edge').count() === edgeCountBefore + 1, 'created edge did not render')

    edgeGraph = await submitLocalInstruction(
      '\u628a\u5f00\u59cb\u5230\u7ed3\u675f\u7684\u8fde\u7ebf\u6807\u7b7e\u6539\u4e3a\u5feb\u901f\u901a\u9053',
    )
    const updatedDirectEdge = edgeGraph.edges.find(edge => edge.id === directEdge.id)
    assert(updatedDirectEdge?.label === '\u5feb\u901f\u901a\u9053', 'natural-language edge label update failed')
    assert(updatedDirectEdge.source === 'start' && updatedDirectEdge.target === 'end', 'edge update changed endpoints')

    edgeGraph = await submitLocalInstruction('\u5220\u9664\u5f00\u59cb\u5230\u7ed3\u675f\u7684\u8fde\u7ebf')
    assert(!edgeGraph.edges.some(edge => edge.id === directEdge.id), 'natural-language edge deletion failed')
    assert(edgeGraph.nodes.length === edgeNodeCount, 'edge deletion changed process nodes')
    assert(edgeGraph.lanes.length === edgeLaneCount, 'edge deletion changed swimlanes')
    assert(await page.locator('.react-flow__edge').count() === edgeCountBefore, 'deleted edge remains rendered')

    stage = 'testing canvas edge inspector'
    const inspectedEdge = page.locator('.react-flow__edge').first()
    await inspectedEdge.dispatchEvent('click')
    const edgeInspector = page.locator('aside[aria-label="\u8fde\u7ebf\u5c5e\u6027"]')
    await edgeInspector.waitFor()
    const inspectedEdgeId = await edgeInspector.locator('.inspector__heading small').textContent()
    assert(inspectedEdgeId, 'edge inspector did not expose the permanent edge ID')
    await edgeInspector.getByLabel('\u6761\u4ef6\u6807\u7b7e').fill('\u753b\u5e03\u5df2\u786e\u8ba4')
    await edgeInspector.getByRole('button', { name: '\u4fdd\u5b58' }).click()
    const storedGraph = await page.evaluate(edgeId => {
      const persisted = JSON.parse(localStorage.getItem('sap-ai-flow-state') || '{}')
      const graph = persisted.state?.graph
      return {
        edge: graph?.edges?.find(edge => edge.id === edgeId),
        nodeCount: graph?.nodes?.length,
        laneCount: graph?.lanes?.length,
      }
    }, inspectedEdgeId)
    assert(storedGraph.edge?.label === '\u753b\u5e03\u5df2\u786e\u8ba4', 'edge inspector did not save the label')
    assert(storedGraph.nodeCount === edgeNodeCount, 'edge inspector changed nodes')
    assert(storedGraph.laneCount === edgeLaneCount, 'edge inspector changed lanes')
    await edgeInspector.getByRole('button', { name: '\u5220\u9664' }).click()
    await page.locator('aside[aria-label="\u6d41\u7a0b\u6982\u51b5"]').waitFor()
    assert(await page.locator('.react-flow__edge').count() === edgeCountBefore - 1, 'edge inspector did not delete the edge')
    assert(await page.locator('.react-flow__node-business').count() === edgeNodeCount, 'edge inspector deletion changed nodes')
    assert(await page.locator('.lane-editor__name').count() === edgeLaneCount, 'edge inspector deletion changed lanes')

    // Create or reuse a stable project fixture through the real API, then exercise it through the UI.
    stage = 'creating project fixture'
    fixture = await page.evaluate(async ({ apiRoot, projectName, processName, viewerUserId }) => {
      const api = async (path, init = {}) => {
        const response = await fetch(`${apiRoot}${path}`, init)
        const payload = response.status === 204 ? null : await response.json()
        if (!response.ok) {
          throw new Error(`${init.method || 'GET'} ${path} failed: ${response.status} ${JSON.stringify(payload)}`)
        }
        return payload
      }

      const projects = await api('/api/v1/projects')
      let project = projects.find(item => item.name === projectName)
      if (!project) {
        project = await api('/api/v1/projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: projectName, customer_name: '\u81ea\u52a8\u9a8c\u6536\u5ba2\u6237' }),
        })
      }
      if (project.external_model_enabled) {
        project = await api(`/api/v1/projects/${project.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ external_model_enabled: false }),
        })
      }

      const members = await api(`/api/v1/projects/${project.id}/members`)
      if (members.some(member => member.user_id === viewerUserId)) {
        await api(`/api/v1/projects/${project.id}/members/${viewerUserId}`, { method: 'DELETE' })
      }

      const processes = await api(`/api/v1/projects/${project.id}/processes`)
      let process = processes.find(item => item.name === processName)
      if (!process) {
        process = await api(`/api/v1/projects/${project.id}/processes`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: processName,
            module: 'MM',
            process_scope: 'P2P',
            initial_graph: {
              schema_version: '2.0',
              graph_id: 'graph_browser_acceptance',
              version: 0,
              title: processName,
              module: 'MM',
              process_scope: 'P2P',
              sap_context: {
                edition: 'S/4HANA',
                release: '2023',
                deployment: 'private_cloud',
                country: 'CN',
              },
              direction: 'LR',
              nodes: [
                { id: 'acceptance_start', type: 'start', label: '\u5f00\u59cb', lane_id: 'acceptance_requester' },
                { id: 'acceptance_end', type: 'end', label: '\u7ed3\u675f', lane_id: 'acceptance_finance' },
              ],
              edges: [
                { id: 'acceptance_edge', source: 'acceptance_start', target: 'acceptance_end' },
              ],
              lanes: [
                { id: 'acceptance_requester', label: '\u9700\u6c42\u90e8\u95e8', color: '#52796f' },
                { id: 'acceptance_finance', label: '\u8d22\u52a1', color: '#a36f3f' },
              ],
              layout: {},
            },
          }),
        })
      }
      return {
        apiRoot,
        projectId: project.id,
        processId: process.id,
        revisionNo: process.current_revision,
      }
    }, { apiRoot, projectName, processName, viewerUserId })

    await openFixture(fixture)
    assert(await page.locator('.react-flow__node-business').count() >= 2, 'fixture graph did not render')

    // Administrator member CRUD and external-model policy confirmation/audit.
    stage = 'testing administrator member management'
    await page.getByRole('button', { name: '\u9879\u76ee\u6210\u5458' }).click()
    const memberDialog = page.getByRole('dialog', { name: '\u9879\u76ee\u6210\u5458' })
    await memberDialog.waitFor()
    assert(
      await memberDialog.locator('.member-dialog__policy-copy').filter({ hasText: '\u4ec5\u672c\u5730' }).count() === 1,
      'new project did not default to local-only model policy',
    )

    const addForm = memberDialog.locator('.member-dialog__add')
    await addForm.locator('input').fill(viewerUserId)
    await addForm.locator('select').selectOption('viewer')
    const addResponsePromise = page.waitForResponse(response =>
      response.url().includes(`/api/v1/projects/${fixture.projectId}/members`)
      && response.request().method() === 'POST',
    )
    await addForm.getByRole('button', { name: '\u6dfb\u52a0\u6210\u5458' }).click()
    assert((await addResponsePromise).ok(), 'adding a viewer failed')
    await memberDialog.locator('.member-row__identity strong').filter({ hasText: viewerUserId }).waitFor()

    const roleSelect = memberDialog.locator(`select[aria-label="${viewerUserId} \u7684\u89d2\u8272"]`)
    const promoteResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/projects/${fixture.projectId}/members/${viewerUserId}`)
      && response.request().method() === 'PUT',
    )
    await roleSelect.selectOption('editor')
    assert((await promoteResponsePromise).ok(), 'updating a member to editor failed')
    await page.locator('.command-dock__status').filter({ hasText: `\u5df2\u66f4\u65b0 ${viewerUserId}` }).waitFor()

    const demoteResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/projects/${fixture.projectId}/members/${viewerUserId}`)
      && response.request().method() === 'PUT',
    )
    await roleSelect.selectOption('viewer')
    assert((await demoteResponsePromise).ok(), 'updating a member back to viewer failed')

    const auditsBefore = await page.evaluate(async ({ apiRoot, projectId }) => {
      const response = await fetch(`${apiRoot}/api/v1/projects/${projectId}/audits`)
      if (!response.ok) throw new Error(`audit request failed: ${response.status}`)
      return (await response.json()).length
    }, fixture)
    const policySwitch = memberDialog.getByRole('switch', { name: '\u5141\u8bb8\u8c03\u7528\u5916\u90e8\u6a21\u578b' })
    stage = 'testing external-model policy'

    const cancelDialogPromise = page.waitForEvent('dialog')
    const cancelClickPromise = policySwitch.click()
    const cancelDialog = await cancelDialogPromise
    assert(cancelDialog.type() === 'confirm', 'external-model opt-in did not show a confirmation dialog')
    await cancelDialog.dismiss()
    await cancelClickPromise
    assert(await policySwitch.getAttribute('aria-checked') === 'false', 'cancelling opt-in changed the policy')

    const enableResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/projects/${fixture.projectId}`)
      && response.request().method() === 'PUT',
    )
    const acceptDialogPromise = page.waitForEvent('dialog')
    const enableClickPromise = policySwitch.click()
    const acceptDialog = await acceptDialogPromise
    assert(acceptDialog.type() === 'confirm', 'external-model opt-in confirmation was not shown')
    await acceptDialog.accept()
    await enableClickPromise
    assert((await enableResponsePromise).ok(), 'enabling external-model policy failed')
    await page.waitForFunction(() =>
      document.querySelector('[role="switch"][aria-label="\u5141\u8bb8\u8c03\u7528\u5916\u90e8\u6a21\u578b"]')
        ?.getAttribute('aria-checked') === 'true',
    )

    const disableResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/projects/${fixture.projectId}`)
      && response.request().method() === 'PUT',
    )
    await policySwitch.click()
    assert((await disableResponsePromise).ok(), 'disabling external-model policy failed')
    await page.waitForFunction(() =>
      document.querySelector('[role="switch"][aria-label="\u5141\u8bb8\u8c03\u7528\u5916\u90e8\u6a21\u578b"]')
        ?.getAttribute('aria-checked') === 'false',
    )

    const auditsAfter = await page.evaluate(async ({ apiRoot, projectId }) => {
      const response = await fetch(`${apiRoot}/api/v1/projects/${projectId}/audits`)
      if (!response.ok) throw new Error(`audit request failed: ${response.status}`)
      return (await response.json()).length
    }, fixture)
    assert(auditsAfter === auditsBefore + 2, `expected two policy audits, got ${auditsBefore}/${auditsAfter}`)

    await assertViewport(390, 844)
    const dialogGeometry = await memberDialog.evaluate(element => ({
      left: element.getBoundingClientRect().left,
      right: element.getBoundingClientRect().right,
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }))
    assert(
      dialogGeometry.left >= 0
      && dialogGeometry.right <= 390
      && dialogGeometry.scrollWidth <= dialogGeometry.clientWidth + 1,
      `member dialog overflows mobile viewport: ${JSON.stringify(dialogGeometry)}`,
    )
    await memberDialog.getByRole('button', { name: '\u5173\u95ed\u9879\u76ee\u6210\u5458' }).click()

    await assertViewport(1024, 768)
    await assertViewport(1440, 900)

    stage = 'testing administrator blueprint downloads'
    const markdown = await downloadBlueprint('\u5bfc\u51fa Markdown \u84dd\u56fe', '.md')
    assert(markdown.text.includes(processName), 'Markdown export does not contain the process name')
    assert(markdown.text.includes('\u9700\u6c42\u90e8\u95e8'), 'Markdown export does not contain the swimlane')
    const docx = await downloadBlueprint('\u5bfc\u51fa Word \u84dd\u56fe', '.docx')
    assert(docx.prefix[0] === 80 && docx.prefix[1] === 75, 'Word export is not a valid ZIP/DOCX payload')

    // A timed-out request must leave the graph unchanged and preserve the command for retry.
    stage = 'testing request timeout recovery'
    const revisionSelect = page.locator('select[aria-label="\u4fee\u8ba2"]')
    const initialRevision = Number(await revisionSelect.inputValue())
    const lifecycleNodeCount = await page.locator('.react-flow__node-business').count()
    const lifecycleCommand = '\u5728\u5f00\u59cb\u540e\u589e\u52a0\u6d4f\u89c8\u5668\u9a8c\u6536\u5ba1\u6279'
    let modifyResponse
    if (managedEnvironment) {
      stage = 'testing explicit request cancellation'
      let finishCancelledRoute
      const cancelledRouteFinished = new Promise(resolve => {
        finishCancelledRoute = resolve
      })
      await page.route(
        `${fixture.apiRoot}/api/v1/processes/${fixture.processId}/modify`,
        async route => {
          try {
            await new Promise(resolve => setTimeout(resolve, 3_500))
            await route.continue()
          } catch {
            // The explicit cancel button aborts this intercepted request.
          } finally {
            finishCancelledRoute()
          }
        },
        { times: 1 },
      )
      const cancelCommand = '\u5728\u5f00\u59cb\u540e\u589e\u52a0\u53d6\u6d88\u6d4b\u8bd5\u8282\u70b9'
      await page.locator('.command-dock textarea').fill(cancelCommand)
      await page.locator('.command-dock button[type=submit]').click()
      await page.getByRole('button', { name: '\u53d6\u6d88' }).click()
      await page.locator('.command-dock__status').filter({ hasText: '\u5df2\u53d6\u6d88\u672c\u6b21\u4fee\u6539' }).waitFor()
      assert(await revisionSelect.inputValue() === String(initialRevision), 'cancel changed the revision')
      assert(
        await page.locator('.react-flow__node-business').count() === lifecycleNodeCount,
        'cancel changed the graph',
      )
      assert(
        await page.locator('.command-dock textarea').inputValue() === cancelCommand,
        'cancel cleared the original command',
      )
      await cancelledRouteFinished

      stage = 'testing revision conflict recovery'
      await page.route(
        `${fixture.apiRoot}/api/v1/processes/${fixture.processId}/modify`,
        route => route.fulfill({
          status: 409,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'REVISION_CONFLICT',
              message: '\u6d41\u7a0b\u5df2\u88ab\u66f4\u65b0\uff0c\u8bf7\u5237\u65b0\u540e\u91cd\u8bd5\u3002',
            },
          }),
        }),
        { times: 1 },
      )
      const conflictCommand = '\u5728\u5f00\u59cb\u540e\u589e\u52a0\u51b2\u7a81\u6d4b\u8bd5\u8282\u70b9'
      await page.locator('.command-dock textarea').fill(conflictCommand)
      await page.locator('.command-dock button[type=submit]').click()
      await page.locator('.command-dock__error').filter({ hasText: '\u5bfc\u51fa\u5f53\u524d JSON \u5907\u4efd' }).waitFor()
      assert(await revisionSelect.inputValue() === String(initialRevision), 'conflict changed the revision')
      assert(
        await page.locator('.react-flow__node-business').count() === lifecycleNodeCount,
        'conflict changed the graph',
      )
      assert(
        await page.locator('.command-dock textarea').inputValue() === conflictCommand,
        'conflict cleared the retry command',
      )

      let finishDelayedRoute
      const delayedRouteFinished = new Promise(resolve => {
        finishDelayedRoute = resolve
      })
      await page.route(
        `${fixture.apiRoot}/api/v1/processes/${fixture.processId}/modify`,
        async route => {
          try {
            await new Promise(resolve => setTimeout(resolve, 3_500))
            await route.continue()
          } catch {
            // The browser aborts this intercepted request when its client deadline expires.
          } finally {
            finishDelayedRoute()
          }
        },
        { times: 1 },
      )
      await page.locator('.command-dock textarea').fill(lifecycleCommand)
      await page.locator('.command-dock button[type=submit]').click()
      await page.locator('.command-dock__error').filter({ hasText: '\u8bf7\u6c42\u8d85\u65f6' }).waitFor({ timeout: 5_000 })
      assert(await revisionSelect.inputValue() === String(initialRevision), 'timeout changed the revision')
      assert(
        await page.locator('.react-flow__node-business').count() === lifecycleNodeCount,
        'timeout changed the graph',
      )
      assert(
        await page.locator('.command-dock textarea').inputValue() === lifecycleCommand,
        'timeout cleared the retry command',
      )
      assert(await page.locator('.command-dock button[type=submit]').isEnabled(), 'retry is disabled after timeout')

      stage = 'retrying after request timeout'
      const retryStartedAt = Date.now()
      const retryResponsePromise = page.waitForResponse(response =>
        response.url().endsWith(`/api/v1/processes/${fixture.processId}/modify`)
        && response.request().method() === 'POST',
      )
      await page.locator('.command-dock button[type=submit]').click()
      modifyResponse = await retryResponsePromise
      assert(modifyResponse.ok(), `retry returned ${modifyResponse.status()}`)
      assert(Date.now() - retryStartedAt < 1_000, 'local persisted retry exceeded 1000 ms')
      await delayedRouteFinished
    } else {
      await page.locator('.command-dock textarea').fill(lifecycleCommand)
      const modifyResponsePromise = page.waitForResponse(response =>
        response.url().endsWith(`/api/v1/processes/${fixture.processId}/modify`)
        && response.request().method() === 'POST',
      )
      await page.locator('.command-dock button[type=submit]').click()
      modifyResponse = await modifyResponsePromise
    }

    // Publish the successful modification, create a new draft, and round-trip through history.
    stage = 'testing persisted release lifecycle'
    assert(modifyResponse.ok(), `persisted modify returned ${modifyResponse.status()}`)
    const modifyPayload = await modifyResponse.json()
    const publishedRevision = initialRevision + 1
    assert(
      modifyPayload.result_revision === publishedRevision,
      `persisted modify returned revision ${modifyPayload.result_revision}, expected ${publishedRevision}`,
    )
    await page.waitForFunction(expected =>
      document.querySelector('select[aria-label="\u4fee\u8ba2"]')?.value === String(expected),
      publishedRevision,
    )
    assert(
      await page.locator('.react-flow__node-business').count() === lifecycleNodeCount + 1,
      'persisted modification did not add exactly one process node',
    )

    const releaseResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/processes/${fixture.processId}/releases`)
      && response.request().method() === 'POST',
    )
    const releaseDialogPromise = page.waitForEvent('dialog')
    const releaseClickPromise = page.getByRole('button', { name: '\u53d1\u5e03\u5f53\u524d\u4fee\u8ba2' }).click()
    const releaseDialog = await releaseDialogPromise
    assert(releaseDialog.type() === 'confirm', 'publishing did not require confirmation')
    await releaseDialog.accept()
    await releaseClickPromise
    const releaseResponse = await releaseResponsePromise
    assert(releaseResponse.status() === 201, `publishing returned ${releaseResponse.status()}`)
    const releasePayload = await releaseResponse.json()
    assert(releasePayload.revision_no === publishedRevision, 'published the wrong revision')
    await page.locator('.header-status').filter({ hasText: '\u53ea\u8bfb \u00b7 \u5df2\u53d1\u5e03' }).waitFor()
    assert(await page.locator('.command-dock textarea').isDisabled(), 'published revision remains editable')

    const draftResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/processes/${fixture.processId}/drafts`)
      && response.request().method() === 'POST',
    )
    await page.getByRole('button', { name: '\u4ece\u53d1\u5e03\u7248\u672c\u521b\u5efa\u65b0\u8349\u7a3f' }).click()
    const draftResponse = await draftResponsePromise
    assert(draftResponse.status() === 201, `creating a draft returned ${draftResponse.status()}`)
    const draftPayload = await draftResponse.json()
    const draftRevision = publishedRevision + 1
    assert(
      draftPayload.revision_no === draftRevision,
      `new draft returned revision ${draftPayload.revision_no}, expected ${draftRevision}`,
    )
    await page.waitForFunction(expected =>
      document.querySelector('select[aria-label="\u4fee\u8ba2"]')?.value === String(expected),
      draftRevision,
    )
    await page.locator('.header-status').filter({ hasText: '\u5df2\u5c31\u7eea' }).waitFor()
    assert(await page.locator('.command-dock textarea').isEnabled(), 'new draft is not editable')

    const historyResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/processes/${fixture.processId}/revisions/${publishedRevision}`)
      && response.request().method() === 'GET',
    )
    await revisionSelect.selectOption(String(publishedRevision))
    assert((await historyResponsePromise).ok(), 'loading the published history revision failed')
    await page.locator('.header-status').filter({ hasText: `\u53ea\u8bfb \u00b7 v${publishedRevision}` }).waitFor()
    assert(await page.locator('.command-dock textarea').isDisabled(), 'history revision remains editable')

    const currentResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/processes/${fixture.processId}/revisions/${draftRevision}`)
      && response.request().method() === 'GET',
    )
    await revisionSelect.selectOption(String(draftRevision))
    assert((await currentResponsePromise).ok(), 'returning to the current draft failed')
    await page.locator('.header-status').filter({ hasText: '\u5df2\u5c31\u7eea' }).waitFor()
    assert(await page.locator('.command-dock textarea').isEnabled(), 'current draft did not restore editability')

    // Switch to the real development identity header and verify viewer behavior end to end.
    stage = 'testing viewer permissions'
    await page.context().setExtraHTTPHeaders({ 'X-User-ID': viewerUserId })
    await openFixture(fixture)
    await page.locator('.header-status').filter({ hasText: '\u53ea\u8bfb \u00b7 \u67e5\u770b\u8005' }).waitFor()
    assert(await page.getByRole('button', { name: '\u9879\u76ee\u6210\u5458' }).count() === 0, 'viewer can see member management')
    assert(
      await page.locator('button[aria-label="\u65b0\u5efa\u6d41\u7a0b"]').evaluateAll(buttons =>
        buttons.length > 0 && buttons.every(button => button.disabled),
      ),
      'viewer can create or reset a flow',
    )
    for (const label of ['\u5bfc\u5165 JSON', '\u81ea\u52a8\u5e03\u5c40', '\u589e\u52a0\u6cf3\u9053', '\u53d1\u5e03\u5f53\u524d\u4fee\u8ba2']) {
      assert(await page.getByRole('button', { name: label }).isDisabled(), `viewer control is enabled: ${label}`)
    }
    assert(await page.locator('.segmented button').evaluateAll(buttons => buttons.every(button => button.disabled)), 'viewer can change layout direction')
    assert(await page.locator('.command-dock textarea').isDisabled(), 'viewer can edit natural-language instructions')
    assert(await page.locator('.command-dock button[type=submit]').isDisabled(), 'viewer can submit modifications')
    assert(await page.getByRole('button', { name: '\u5bfc\u51fa Markdown \u84dd\u56fe' }).isEnabled(), 'viewer cannot export blueprints')

    stage = 'testing viewer edge inspector'
    const viewerEdgeCount = await page.locator('.react-flow__edge').count()
    const viewerEdge = page.locator('.react-flow__edge').first()
    await viewerEdge.dispatchEvent('click')
    const viewerEdgeInspector = page.locator('aside[aria-label="\u8fde\u7ebf\u5c5e\u6027"]')
    await viewerEdgeInspector.waitFor()
    assert(await viewerEdgeInspector.getByLabel('\u6761\u4ef6\u6807\u7b7e').count() === 0, 'viewer can edit the edge label')
    assert(await viewerEdgeInspector.getByRole('button', { name: '\u5220\u9664' }).count() === 0, 'viewer can delete an edge')
    await page.keyboard.press('Delete')
    assert(await page.locator('.react-flow__edge').count() === viewerEdgeCount, 'viewer deleted an edge with the keyboard')

    const forbiddenMembers = await page.request.get(`${fixture.apiRoot}/api/v1/projects/${fixture.projectId}/members`, {
      headers: { 'X-User-ID': viewerUserId },
    })
    assert(forbiddenMembers.status() === 403, `viewer member API returned ${forbiddenMembers.status()}`)
    const forbiddenPolicy = await page.request.put(`${fixture.apiRoot}/api/v1/projects/${fixture.projectId}`, {
      headers: { 'Content-Type': 'application/json', 'X-User-ID': viewerUserId },
      data: { external_model_enabled: true },
    })
    assert(forbiddenPolicy.status() === 403, `viewer policy API returned ${forbiddenPolicy.status()}`)

    const viewerMarkdown = await downloadBlueprint('\u5bfc\u51fa Markdown \u84dd\u56fe', '.md')
    assert(viewerMarkdown.text.includes(processName), 'viewer Markdown export is incomplete')
    await assertViewport(390, 844)

    // Return to the administrator and remove the temporary viewer through the UI.
    stage = 'removing temporary viewer'
    await page.context().setExtraHTTPHeaders({ 'X-User-ID': adminUserId })
    await assertViewport(1440, 900)
    await openFixture(fixture)
    await page.getByRole('button', { name: '\u9879\u76ee\u6210\u5458' }).click()
    const cleanupDialog = page.getByRole('dialog', { name: '\u9879\u76ee\u6210\u5458' })
    await cleanupDialog.waitFor()
    const deleteResponsePromise = page.waitForResponse(response =>
      response.url().endsWith(`/api/v1/projects/${fixture.projectId}/members/${viewerUserId}`)
      && response.request().method() === 'DELETE',
    )
    const removeDialogPromise = page.waitForEvent('dialog')
    const removeClickPromise = cleanupDialog.getByRole('button', { name: `\u79fb\u9664 ${viewerUserId}` }).click()
    const removeDialog = await removeDialogPromise
    await removeDialog.accept()
    await removeClickPromise
    assert((await deleteResponsePromise).status() === 204, 'removing the temporary viewer failed')
    await page.waitForFunction(viewerUserId =>
      ![...document.querySelectorAll('.member-row__identity strong')]
        .some(element => element.textContent === viewerUserId),
      viewerUserId,
    )

    stage = 'checking browser errors'
    assert(consoleErrors.length === 0, `browser console errors: ${consoleErrors.join(' | ')}`)
    assert(pageErrors.length === 0, `uncaught page errors: ${pageErrors.join(' | ')}`)
  } catch (error) {
    const browserState = await page.evaluate(() => ({
      status: document.querySelector('.command-dock__status span')?.textContent ?? '',
      error: document.querySelector('.command-dock__error')?.textContent ?? '',
      nodes: document.querySelectorAll('.react-flow__node-business').length,
      lanes: [...document.querySelectorAll('.lane-editor__name')].map(element => element.value),
    })).catch(() => ({ unavailable: true }))
    throw new Error(`[${stage}] ${error.message}; browser=${JSON.stringify(browserState)}`)
  } finally {
    await page.context().setExtraHTTPHeaders({ 'X-User-ID': adminUserId })
    if (fixture) {
      await page.evaluate(async ({ apiRoot, projectId, viewerUserId }) => {
        const memberResponse = await fetch(`${apiRoot}/api/v1/projects/${projectId}/members`)
        if (memberResponse.ok) {
          const members = await memberResponse.json()
          if (members.some(member => member.user_id === viewerUserId)) {
            await fetch(`${apiRoot}/api/v1/projects/${projectId}/members/${viewerUserId}`, { method: 'DELETE' })
          }
        }
        const projectResponse = await fetch(`${apiRoot}/api/v1/projects/${projectId}`)
        if (projectResponse.ok && (await projectResponse.json()).external_model_enabled) {
          await fetch(`${apiRoot}/api/v1/projects/${projectId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ external_model_enabled: false }),
          })
        }
      }, { projectId: fixture.projectId, viewerUserId }).catch(() => {})
    }
    page.off('console', captureConsoleError)
    page.off('pageerror', capturePageError)
  }
}
