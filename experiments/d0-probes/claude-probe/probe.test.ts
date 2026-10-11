import { test, expect } from 'claude-code/testing'

const PANE = {
  title: 'xmuse probe',
  isFocused: false,
  bodyColumns: 60,
  placement: 'dock',
  scroll: { offset: 0, bodyRows: 20 },
  view: {},
} as const

const BAND = {
  hasSurvey: false,
  isWorking: false,
  maxRows: 5,
  bodyColumns: 80,
  scroll: { offset: 0, bodyRows: 5 },
  view: {},
} as const

test('Pane with Select, Input, Button and Markdown mounts on desktop and terminal', async $ => {
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'xmuse-probe',
      surface,
      component: 'Pane',
      requestId: 'xmuse-probe',
      props: PANE,
      viewport: { columns: 60, rows: 30, isFullscreen: true },
    })
    console.log(surface, JSON.stringify(await ui.drawn()).slice(0, 1500))
    expect(await ui.find({ type: 'Select', key: 'provider' })).toBeDefined()
    expect(await ui.find({ type: 'Input', key: 'room-name' })).toBeDefined()
    expect(await ui.find({ type: 'Markdown' })).toBeDefined()
    await ui.select({ key: 'provider', value: 'opencode' })
    await ui.input({ key: 'room-name', text: 'demo-room' })
    await ui.press({ key: 'invite' })
    await ui.press({ key: 'approve' })
    expect((await ui.find({ type: 'Text', text: /presses: \d+/ }))).toBeDefined()
    expect((await ui.find({ type: 'Text', text: /xmuse room: demo-room/ }))).toBeDefined()
    await ui.unmount()
  }
})

test('AbovePrompt band mounts on desktop and terminal', async $ => {
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'xmuse-probe',
      surface,
      component: 'AbovePrompt',
      props: BAND,
      viewport: { columns: 80, rows: 30, isFullscreen: true },
    })
    expect(await ui.find({ type: 'Button', key: 'open' })).toBeDefined()
    await ui.unmount()
  }
})

test('mobile: Input/Select are not in its table, so they draw nothing there', async $ => {
  const ui = await $.ui.mount({
    plugin: 'xmuse-probe',
    surface: 'mobile',
    component: 'Pane',
    requestId: 'xmuse-probe',
    props: PANE,
  })
  console.log('mobile', JSON.stringify(await ui.drawn()).slice(0, 700))
  expect(await ui.find({ type: 'Input' })).toBeUndefined()
  await ui.unmount()
})

test('/xmuse command answers with args', async ($, on) => {
  on('session.id', () => ({ value: 'test-session-id' }))
  const r = await $.command.run({ command: 'xmuse', args: 'join K7Q2' })
  expect(r.text).toContain('K7Q2')
})
